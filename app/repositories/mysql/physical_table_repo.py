"""物理表仓储：建表、灌数据、删表（DDL 与批量插入集中在这里）。"""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PhysicalTableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_table(self, physical: str, columns: Sequence[tuple[str, str]]) -> None:
        """columns: [(列名, SQL 类型), ...]"""
        columns_sql = ", ".join(f"`{name}` {sql_type}" for name, sql_type in columns)
        await self.session.execute(
            text(f"CREATE TABLE IF NOT EXISTS `{physical}` ({columns_sql})")
        )
        await self.session.flush()

    async def insert_rows(
        self, physical: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        cols = ", ".join(f"`{c}`" for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        raw = await self.session.connection()
        await raw.exec_driver_sql(
            f"INSERT INTO `{physical}` ({cols}) VALUES ({placeholders})", rows
        )
        await self.session.flush()
        return len(rows)

    async def execute_select(self, sql: str, *, limit: int = 100) -> list[dict]:
        """在当前 session 里执行只读查询（CSV 采样用，能看到未提交的数据）。"""
        result = await self.session.execute(text(sql))
        rows = result.fetchmany(limit)
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in rows]

    async def drop_if_exists(self, physical: str) -> None:
        """删掉可能残留的物理表（上次上传中途失败留下的孤儿表）。"""
        await self.session.execute(text(f"DROP TABLE IF EXISTS `{physical}`"))

    async def drop_table(self, physical: str) -> None:
        await self.session.execute(text(f"DROP TABLE IF EXISTS `{physical}`"))
