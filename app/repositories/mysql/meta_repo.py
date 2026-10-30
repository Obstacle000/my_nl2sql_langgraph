"""元数据仓储：表 / 字段 / 指标。"""

import json

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.meta import ColumnInfoEntity, MetricInfoEntity
from app.models.meta import ColumnInfo, MetricInfo, TableInfo

# 提问:为什么mysql里要存元数据表,Qdrant里存不够吗
# 我们先来看point结构:
# {
#     id:...,
#     vector:...
#     payload:
#         {
#           "user_id": 1,
#           "dataset_id": 2,
#           "datasource_id": 3,
#           "id": "orders.amount",
#           "table_id": "orders",
#           "name": "amount",
#           "type": "decimal(10,2)",
#           "role": "measure",
#           "description": "订单金额",
#           "examples": ["199.00", "88.50"],
#           "alias": ["销售额", "收入"]
#         }
# }
# 可以发现,想要从point里数据都是mysql数据的衍生数据
# · 删了 Qdrant → 可以用 MySQL 里的描述重新算向量，完全恢复
# · 删了 MySQL   → 描述、别名、关系全没了，Qdrant 的 payload 只是副本

# 往Qdrant存的时候数据源就是元数据表
# 上传 CSV / 同步 schema
#   → 写 MySQL（column_info / table_info / dataset_tables）并提交
#   → reindex_dataset(user_id, dataset_id)
#        → meta_repo.list_columns(dataset_id)      ← 从 MySQL 读
#        → embedding → Qdrant
#        → examples → ES
class MetaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- 写 --
    async def save_table(
        self, dataset_id: int, table_id: str, name: str, role: str, description: str
    ) -> None:
        self.session.add(
            TableInfo(
                id=table_id,
                dataset_id=dataset_id,
                name=name,
                role=role,
                description=description,
            )
        )
        await self.session.flush()

    async def save_table_with_columns(
        self,
        dataset_id: int,
        table_id: str,
        name: str,
        role: str,
        description: str,
        columns: list[ColumnInfoEntity],
        datasource_id: int = 0,
    ) -> None:
        """一张表 + 它的字段，同一事务写入。服务层只传实体，不碰 ORM。"""
        self.session.add(
            TableInfo(
                id=table_id,
                dataset_id=dataset_id,
                name=name,
                role=role,
                description=description,
            )
        )
        self.session.add_all(
            [
                ColumnInfo(
                    id=col.id,
                    dataset_id=dataset_id,
                    table_id=col.table_id,
                    name=col.name,
                    type=col.type,
                    role=col.role,
                    description=col.description,
                    examples=json.dumps(col.examples, ensure_ascii=False),
                    alias=json.dumps(col.alias, ensure_ascii=False),
                )
                for col in columns
            ]
        )

        await self.session.flush()
    async def list_columns_by_table(
        self, dataset_id: int, table_id: str, datasource_id: int = 0
    ) -> list[ColumnInfoEntity]:
        result = await self.session.execute(
            select(ColumnInfo).where(
                ColumnInfo.dataset_id == dataset_id, ColumnInfo.table_id == table_id
            )
        )
        entities = [self._to_entity(row) for row in result.scalars().all()]
        for entity in entities:
            entity.dataset_id = dataset_id
            entity.datasource_id = datasource_id
        return entities

    async def add_columns(self, dataset_id: int, columns: list[ColumnInfoEntity]) -> int:
        """只新增字段，不动已有字段。"""
        if not columns:
            return 0
        self.session.add_all(
            [
                ColumnInfo(
                    id=col.id,
                    dataset_id=dataset_id,
                    table_id=col.table_id,
                    name=col.name,
                    type=col.type,
                    role=col.role,
                    description=col.description,
                    examples=json.dumps(col.examples, ensure_ascii=False),
                    alias=json.dumps(col.alias, ensure_ascii=False),
                )
                for col in columns
            ]
        )
        await self.session.flush()
        return len(columns)

    async def update_columns_meta(
        self, dataset_id: int, columns: list[ColumnInfoEntity]
    ) -> int:
        """按 id 更新类型/描述（列名不变时用）。"""
        if not columns:
            return 0
        for col in columns:
            row = await self.session.get(ColumnInfo, col.id)
            if row is None or row.dataset_id != dataset_id:
                continue
            row.type = col.type
            row.description = col.description
        await self.session.flush()
        return len(columns)

    async def delete_table_meta(self, dataset_id: int, table_id: str) -> int:
        """删一张表的元数据行（table_info + column_info）。"""
        deleted = 0
        result = await self.session.execute(
            delete(ColumnInfo).where(
                ColumnInfo.dataset_id == dataset_id, ColumnInfo.table_id == table_id
            )
        )
        deleted += result.rowcount or 0
        await self.session.execute(
            delete(TableInfo).where(
                TableInfo.dataset_id == dataset_id, TableInfo.id == table_id
            )
        )
        await self.session.flush()
        return deleted

    async def delete_columns(
        self, dataset_id: int, table_id: str, names: list[str]
    ) -> int:
        """删除指定表的若干字段（源表删列时用，调用方需显式确认）。"""
        if not names:
            return 0
        ids = [f"{table_id}.{name}" for name in names]
        result = await self.session.execute(
            delete(ColumnInfo).where(
                ColumnInfo.dataset_id == dataset_id, ColumnInfo.id.in_(ids)
            )
        )
        await self.session.flush()
        return result.rowcount or 0

    async def delete_by_dataset(self, dataset_id: int) -> None:
        """删掉一个数据集的所有元数据行（column/table/metric）。"""
        for table in ("column_info", "table_info", "metric_info"):
            await self.session.execute(
                text(f"DELETE FROM {table} WHERE dataset_id = :d"), {"d": dataset_id}
            )
        await self.session.flush()

    async def save_columns(self, rows: list[ColumnInfo]) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def save_metric(self, metric: MetricInfo) -> None:
        self.session.add(metric)
        await self.session.flush()

    # -- 读 --
    async def get_columns_by_ids(
        self, dataset_id: int, column_ids: list[str]
    ) -> list[ColumnInfoEntity]:
        if not column_ids:
            return []
        result = await self.session.execute(
            select(ColumnInfo).where(
                ColumnInfo.dataset_id == dataset_id, ColumnInfo.id.in_(column_ids)
            )
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    async def list_columns(
        self, dataset_id: int, datasource_id: int = 0
    ) -> list[ColumnInfoEntity]:
        """列出数据集全部字段：重建索引时以 MySQL 为唯一事实源。"""
        result = await self.session.execute(
            select(ColumnInfo)
            .where(ColumnInfo.dataset_id == dataset_id)
            .order_by(ColumnInfo.table_id, ColumnInfo.name)
        )
        entities = [self._to_entity(row) for row in result.scalars().all()]
        for entity in entities:
            entity.dataset_id = dataset_id
            entity.datasource_id = datasource_id
        return entities

    async def get_key_columns(self, dataset_id: int, table_id: str) -> list[ColumnInfoEntity]:
        result = await self.session.execute(
            select(ColumnInfo).where(
                ColumnInfo.dataset_id == dataset_id,
                ColumnInfo.table_id == table_id,
                ColumnInfo.role.in_(["primary_key", "foreign_key"]),
            )
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    async def list_metrics(self, dataset_id: int) -> list[MetricInfoEntity]:
        result = await self.session.execute(
            select(MetricInfo).where(MetricInfo.dataset_id == dataset_id)
        )
        rows = result.scalars().all()
        return [
            MetricInfoEntity(
                id=row.id,
                name=row.name,
                description=row.description,
                relevant_columns=json.loads(row.relevant_columns or "[]"),
                alias=json.loads(row.alias or "[]"),
            )
            for row in rows
        ]

    @staticmethod
    def _to_entity(row: ColumnInfo) -> ColumnInfoEntity:
        return ColumnInfoEntity(
            id=row.id,
            table_id=row.table_id,
            name=row.name,
            type=row.type,
            role=row.role,
            description=row.description,
            examples=json.loads(row.examples or "[]"),
            alias=json.loads(row.alias or "[]"),
        )
