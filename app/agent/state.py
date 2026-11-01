"""图状态：只放可序列化的业务数据。

每个字段都标注了"谁写 / 谁读"，方便顺着节点排查问题。
"""

from typing import Any, TypedDict


class Nl2SqlState(TypedDict, total=False):
    # ---------------- 输入（路由写入） ----------------
    question: str                      # 用户这一轮的原话
    user_id: int                       # 当前用户（缓存 key、元数据过滤都要）
    dataset_id: int                    # 数据集（决定查哪套元数据/数据源）
    schema_version: int                # 元数据版本（结构变了缓存自然失效）

    # ---------------- 多轮（路由写入，改写节点读写） ----------------
    conversation_id: int | None        # 会话 id；为空表示单轮问数
    history: list[dict[str, Any]]      # 最近几轮成功问答：[{role, content, sql}]
    last_clarify: str                  # 上一轮系统反问的内容（用户这句可能在回答它）
    clarify_rounds: int                # 本会话已反问次数；>=2 时不再追问，改用默认假设

    # ---------------- 改写（rewrite_question 写，下游读） ----------------
    standalone_question: str           # 补全后可独立执行的问题（下游全用它，不再用 question）
    complete: bool                     # False=信息不全 → 走 ask_clarify
    missing: str                       # 缺什么（"时间范围"），用于拼反问话术
    context_sig: str                   # 本轮继承条件的指纹；空表示无上下文，与单轮共用缓存
    assumed: dict[str, Any]            # 连续反问后采用的默认假设（reason/assumption/missing）
    topic_switch: bool                 # 是否换话题（True 时不继承上下文，context_sig 为空）

    # ---------------- 召回（extract_keywords / recall_* 写） ----------------
    keywords: list[str]                # 从问题里抽出的关键词（表名/字段名/指标名）
    retrieved_column_infos: list[dict[str, Any]]   # Qdrant 召回的字段（可含别名多条）
    retrieved_metric_infos: list[dict[str, Any]]   # Qdrant 召回的指标
    retrieved_value_infos: list[dict[str, Any]]    # ES 召回的具体取值（"华北"→ region_name）

    # ---------------- 上下文（merge_retrieved_info / add_extra_context 写） ----------------
    table_infos: list[dict[str, Any]]  # 进 prompt 的表结构：表名 + 字段 + 样例值（截断后）
    metric_infos: list[dict[str, Any]] # 命中的指标口径（expression/description）
    matched_values: list[dict[str, Any]]  # 已确认的取值命中：值 + 所属表.字段
    table_relations: list[str]         # JOIN 依据：["t_ord.cust_no = t_cust.cust_no", ...]
    date_info: dict[str, str]          # 今天/本月等日期上下文，供模型写时间条件
    db_info: dict[str, str]            # 方言与版本（MySQL 8.0 / SQLite 等）

    # ---------------- SQL 闭环（generate/validate/correct/run 写） ----------------
    sql: str                           # 当前 SQL（会被 correct_sql 覆盖）
    error: str | None                  # EXPLAIN 校验失败信息；None 表示通过
    fix_rounds: int                    # 已修正次数（validate 失败 → correct_sql）
    check_rounds: int                  # 已自检重试次数（check_result 命中 → correct_sql）
    retry_reason: str | None           # 自检发现的问题；有值且重试用尽 → suspect

    # ---------------- 结果与缓存（check_cache / run_sql / write_cache 写） ----------------
    rows: list[dict[str, Any]]         # 执行结果（最多 MAX_ROWS 行）
    hit_cache: bool                    # 是否命中缓存（hit 时不生成、不执行）
    cache_kind: str                    # exact / semantic / miss
    started_at: float                  # 请求开始时间（算耗时、写审计）
