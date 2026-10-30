"""数据集仓储：所有方法都必须带 user_id，防止越权。"""


from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, DatasetTable


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_user(self, user_id: int) -> list[Dataset]:
        result = await self.session.execute(
            select(Dataset).where(Dataset.user_id == user_id).order_by(Dataset.id.desc())
        )
        return list(result.scalars().all())

    async def get(self, user_id: int, dataset_id: int) -> Dataset | None:
        result = await self.session.execute(
            select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        name: str,
        description: str = "",
        datasource_id: int | None = None,
    ) -> Dataset:
        dataset = Dataset(
            user_id=user_id,
            name=name,
            description=description,
            datasource_id=datasource_id,
        )
        self.session.add(dataset)
        await self.session.flush()
        return dataset

    async def create_csv_dataset(self, user_id: int, name: str, description: str = "") -> Dataset:
        """建 kind=csv 的数据源 + 空数据集（同一事务）。"""
        from app.models.datasource import DataSource

        async with self.session.begin():
            datasource = DataSource(user_id=user_id, kind="csv", name=name, status="ok")
            self.session.add(datasource)
            await self.session.flush()
            dataset = Dataset(
                user_id=user_id,
                name=name,
                description=description,
                datasource_id=datasource.id,
            )
            self.session.add(dataset)
        return dataset

    async def create_with_datasource(
        self, user_id: int, name: str, description: str, datasource_id: int
    ) -> Dataset:
        """在已有数据源下建数据集（独立事务）。"""
        async with self.session.begin():
            dataset = Dataset(
                user_id=user_id,
                name=name,
                description=description,
                datasource_id=datasource_id,
            )
            self.session.add(dataset)
        return dataset

    async def list_by_datasource(self, user_id: int, datasource_id: int) -> list[Dataset]:
        result = await self.session.execute(
            select(Dataset).where(
                Dataset.user_id == user_id, Dataset.datasource_id == datasource_id
            )
        )
        return list(result.scalars().all())

    async def add_table(
        self, dataset_id: int, table_name: str, physical_name: str, row_count: int
    ) -> DatasetTable:
        table = DatasetTable(
            dataset_id=dataset_id,
            table_name=table_name,
            physical_name=physical_name,
            row_count=row_count,
        )
        self.session.add(table)
        await self.session.flush()
        return table

    async def list_tables(self, dataset_id: int) -> list[DatasetTable]:
        result = await self.session.execute(
            select(DatasetTable).where(DatasetTable.dataset_id == dataset_id)
        )
        return list(result.scalars().all())
    # bump_schema_version 是把 datasets.schema_version 加一，用来让旧缓存自动失效。
    # schema_version 进缓存 key：
    # sql:{user_id}:{dataset_id}:{schema_version}:{问题hash}
    #  → 版本一变，旧 key 永远查不到
    #  → 旧缓存不用删，靠 TTL 自然过期
    async def delete_table(self, dataset_id: int, physical_name: str) -> None:
        from sqlalchemy import delete as sa_delete

        await self.session.execute(
            sa_delete(DatasetTable).where(
                DatasetTable.dataset_id == dataset_id,
                DatasetTable.physical_name == physical_name,
            )
        )
        await self.session.commit()

    async def bump_schema_version(self, dataset_id: int) -> int:
        """schema 变更后 +1 并提交；返回新版本（用于缓存失效）。"""
        dataset = await self.session.get(Dataset, dataset_id)
        if dataset is None:
            return 0
        dataset.schema_version += 1
        version = dataset.schema_version
        await self.session.commit()
        return version

    async def delete(self, user_id: int, dataset_id: int) -> None:
        await self.session.execute(
            delete(DatasetTable).where(DatasetTable.dataset_id == dataset_id)
        )
        await self.session.execute(
            delete(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id)
        )
