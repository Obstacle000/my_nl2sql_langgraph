"""图状态：只放可序列化的业务数据。"""

from typing import Any, TypedDict


class Nl2SqlState(TypedDict, total=False):
    # 输入
    question: str
    user_id: int
    dataset_id: int
    schema_version: int

    # 召回
    keywords: list[str]
    retrieved_column_infos: list[dict[str, Any]]
    retrieved_metric_infos: list[dict[str, Any]]
    retrieved_value_infos: list[dict[str, Any]]

    # 上下文
    table_infos: list[dict[str, Any]]
    metric_infos: list[dict[str, Any]]
    matched_values: list[dict[str, Any]]
    date_info: dict[str, str]
    db_info: dict[str, str]

    # SQL 闭环
    sql: str
    error: str | None
    fix_rounds: int
    check_rounds: int
    retry_reason: str | None

    # 结果与缓存
    rows: list[dict[str, Any]]
    hit_cache: bool
