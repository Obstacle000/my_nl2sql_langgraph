"""CSV 数据源：数据在本地库的物理表 ds{dataset_id}_t*。"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.datasources.base import ColumnSchema, TableSchema
from app.repositories.mysql.dataset_repo import DatasetRepository


class CSVDataSource:
    kind = "csv"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_id: int,
        datasource_id: int,
        dataset_id: int,
    ) -> None:
        self.session_factory = session_factory
        self.user_id = user_id
        self.datasource_id = datasource_id
        self.dataset_id = dataset_id

    async def test_connection(self) -> None:
        async with self.session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def _allowed_tables(self) -> set[str]:
        async with self.session_factory() as session:
            tables = await DatasetRepository(session).list_tables(self.dataset_id)
        return {t.physical_name for t in tables}

    def _check_readonly(self, sql: str) -> None:
        if not sql.lower().lstrip().startswith(("select", "with")):
            raise ValueError("只允许 SELECT 查询")

    async def discover_schema(self) -> list[TableSchema]:
        schemas: list[TableSchema] = []
        async with self.session_factory() as session:
            tables = await DatasetRepository(session).list_tables(self.dataset_id)
            for table in tables:
                cols = await session.execute(
                    text(
                        "SELECT column_name, column_type, column_comment "
                        "FROM information_schema.columns "
                        "WHERE table_schema = DATABASE() AND table_name = :t "
                        "ORDER BY ordinal_position"
                    ),
                    {"t": table.physical_name},
                )
                schemas.append(
                    TableSchema(
                        name=table.physical_name,
                        comment=table.table_name,
                        columns=[
                            ColumnSchema(name=r[0], type=r[1], comment=r[2] or "")
                            for r in cols.fetchall()
                        ],
                    )
                )
        return schemas

    async def execute(
        self, sql: str, *, limit: int = 1000, timeout_s: int = 30
    ) -> list[dict[str, Any]]:
        self._check_readonly(sql)
        allowed = await self._allowed_tables()
        lowered = sql.lower()
        if not any(name in lowered for name in allowed):
            raise ValueError("SQL 未引用本数据集中的表")
        async with self.session_factory() as session:
            result = await session.execute(text(sql))
            rows = result.fetchmany(limit)
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in rows]

    async def validate(self, sql: str) -> None:
        self._check_readonly(sql)
        async with self.session_factory() as session:
            await session.execute(text(f"EXPLAIN {sql}"))

    async def db_info(self) -> dict[str, str]:
        async with self.session_factory() as session:
            version = (await session.execute(text("SELECT VERSION()"))).scalar()
            dialect = session.bind.dialect.name
        return {"dialect": str(dialect), "version": str(version)}
