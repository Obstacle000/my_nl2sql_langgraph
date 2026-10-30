"""数据源协议：上层（召回/生成/执行）只依赖这个接口。"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ColumnSchema:
    name: str
    type: str
    comment: str = ""


@dataclass
class TableSchema:
    name: str
    comment: str = ""
    columns: list[ColumnSchema] = field(default_factory=list)


class DataSource(Protocol):
    kind: str
    datasource_id: int

    async def test_connection(self) -> None: ...

    async def discover_schema(self) -> list[TableSchema]: ...

    async def execute(
        self, sql: str, *, limit: int = 1000, timeout_s: int = 30
    ) -> list[dict[str, Any]]: ...

    async def validate(self, sql: str) -> None:
        """SQL 不可用时抛异常（EXPLAIN 校验）。"""
        ...

    async def db_info(self) -> dict[str, str]:
        """方言与版本，供提示词使用。"""
        ...
