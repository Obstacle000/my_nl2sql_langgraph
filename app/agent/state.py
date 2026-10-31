"""图状态：只放可序列化的业务数据。"""

from typing import Any, TypedDict


class Nl2SqlState(TypedDict, total=False):
    # 输入
    question: str
    conversation_id: int | None
    history: list[dict[str, Any]]      # 最近几轮：[{role, content, sql}]

    # 多轮改写
    standalone_question: str           # 补全后可独立执行的问题
    complete: bool                     # False 表示信息不全，走反问
    missing: str                       # 缺什么（"时间范围"）
    context_sig: str                   # 本轮继承条件的指纹（空=无上下文，与单轮共用缓存）
    clarify_rounds: int                # 本会话已反问次数（>=2 不再追问）
    last_clarify: str                  # 上一轮系统问了什么（用户这句可能是在回答它）
    assumed: dict[str, Any]            # 连续反问后采用的默认假设
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
    table_relations: list[str]
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
    cache_kind: str          # exact / semantic / miss
    started_at: float
