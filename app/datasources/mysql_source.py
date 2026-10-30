"""MySQL 数据源：只读连接用户的库，动态发现 schema。"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.datasources.base import ColumnSchema, TableSchema


# DataSource 协议的 MySQL 实现：连用户的库、读表结构、执行查询。
class MySQLDataSource:
    kind = "mysql"

    def __init__(self, datasource_id: int, config: dict) -> None:
        self.datasource_id = datasource_id
        self.config = config
        self.engine: AsyncEngine | None = None

    def _engine(self) -> AsyncEngine:
        if self.engine is None:
            cfg = self.config
            url = (
                f"mysql+asyncmy://{cfg['user']}:{cfg['password']}"
                f"@{cfg['host']}:{int(cfg.get('port', 3306))}/{cfg['database']}"
                "?charset=utf8mb4"
            )
            self.engine = create_async_engine(url, pool_size=3, pool_pre_ping=True)
        return self.engine

    async def test_connection(self) -> None:
        async with self._engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def discover_schema(self) -> list[TableSchema]:
        sql = text(
            "SELECT table_name, column_name, column_type, column_comment "
            "FROM information_schema.columns "
            "WHERE table_schema = :db ORDER BY table_name, ordinal_position"
        )
        grouped: dict[str, TableSchema] = {}
        async with self._engine().connect() as conn:
            rows = await conn.execute(sql, {"db": self.config["database"]})
            for table_name, column_name, column_type, comment in rows:
                # dict.setdefault(key, default)：key 存在就返回它的值，不存在就先存 default 再返回。
                grouped.setdefault(table_name, TableSchema(name=table_name)).columns.append(
                    ColumnSchema(name=column_name, type=column_type, comment=comment or "")
                )
        return list(grouped.values())

    async def execute(
        self, sql: str, *, limit: int = 1000, timeout_s: int = 30
    ) -> list[dict[str, Any]]:
        if not sql.lower().lstrip().startswith("select"):
            raise ValueError("只允许 SELECT 查询")
        async with self._engine().connect() as conn:
            # 执行层兜底：即使模型漏写 LIMIT，也不返回超过 limit 行
            result = await conn.execute(text(sql))
            rows = result.fetchmany(limit)
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in rows]
