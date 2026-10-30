"""图状态：只放业务数据（可序列化）。"""

from typing import TypedDict


class Nl2SqlState(TypedDict, total=False):
    question: str
    user_id: int
    dataset_id: int
    schema_version: int
    keywords: list[str]
    candidates: list[dict]
    table_context: list[dict]
    sql: str
    error: str | None
    fix_rounds: int
    rows: list[dict]
    hit_cache: bool
