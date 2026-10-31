"""完整图：缓存 → 关键词 → 三路召回 → 合并 → 过滤 → 上下文 → 生成 → 校验/修正 → 执行 → 自检 → 缓存。"""
#                       ┌─────────────┐
#                       │    START    │
#                       └──────┬──────┘
#                              │ question / user_id / dataset_id / schema_version
#                              │ (+ history / conversation_id，多轮时)
#                              ▼
#                ┌──────────────────────────┐   
#                │     rewrite_question     │
#                │ 最近 3 轮 + 当前句 → 独立问题│
#                │ 输出 complete / missing   │
#                └───────────┬──────────────┘
#                            │
#          不完整 ────────────┴──────────── 完整
#            │                                │
#            ▼                                ▼
#   ┌──────────────────┐         ┌──────────────────────────┐
#   │   ask_clarify    │         │       check_cache        │
#   │ 反问，不生成 SQL   │         │  精确 hash → 语义向量      │
#   └────────┬─────────┘         └───────────┬──────────────┘
#            │                                 │
#            │                命中 ────────────┴──────────── 未命中
#            │                  │                              │
#            │                  │                              ▼
#            │                  │                 ┌──────────────────────────┐
#            │                  │                 │     extract_keywords     │
#            │                  │                 │  jieba + 原句兜底 → keywords│
#            │                  │                 └────────────┬─────────────┘
#            │                  │                              │
#            │                  │        ┌─────────────────────┼─────────────────────┐
#            │                  │        ▼                     ▼                     ▼
#            │                  │ ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
#            │                  │ │recall_column │   │ recall_value │   │recall_metric │
#            │                  │ │ Qdrant 字段   │   │  ES 取值      │   │ Qdrant 指标   │
#            │                  │ │ filter:租户   │   │ 只留问题提到的 │   │ filter:租户   │
#            │                  │ └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
#            │                  │        │                  │                  │
#            │                  │        └──────────────────┼──────────────────┘
#            │                  │                           ▼
#            │                  │             ┌──────────────────────────────┐
#            │                  │             │    merge_retrieved_info      │
#            │                  │             │ 去重 + 补指标依赖字段          │
#            │                  │             │ + 命中取值 → matched_values   │
#            │                  │             │ + 补主外键（role）→ table_infos │
#            │                  │             │ + 补日期列（dt/date_id）       │
#            │                  │             │ + 读 table_relation → 表关系   │
#            │                  │             └──────────────┬───────────────┘
#            │                  │                            │
#            │                  │        ┌───────────────────┴──────────────────┐
#            │                  │        ▼                                      ▼
#            │                  │ ┌────────────────────┐          ┌────────────────────────┐
#            │                  │ │   filter_table     │          │  filter_metric（条件边）  │
#            │                  │ │ 单表→短路不调LLM    │          │ 无指标召回→直接跳过        │
#            │                  │ │ 多表→LLM 选表+字段   │          │ 有指标→LLM 选指标         │
#            │                  │ │ 时间词→保留日期列     │          │                        │
#            │                  │ └─────────┬──────────┘          └───────────┬────────────┘
#            │                  │           │                                 │
#            │                  │           └────────────────┬────────────────┘
#            │                  │                            ▼
#            │                  │            ┌──────────────────────────────┐
#            │                  │            │     add_extra_context        │
#            │                  │            │ + date_info（今天/季度）        │
#            │                  │            │ + db_info（方言/版本）          │
#            │                  │            └──────────────┬───────────────┘
#            │                  │                           ▼
#            │                  │            ┌──────────────────────────────┐
#            │                  │            │        generate_sql          │
#            │                  │            │ table_infos + metric_infos   │
#            │                  │            │ + matched_values + relations │
#            │                  │            │ + 字段约定/口径规则             │
#            │                  │            └──────────────┬───────────────┘
#            │                  │                           ▼
#            │                  │            ┌──────────────────────────────┐
#            │                  │            │        validate_sql          │
#            │                  │            │   EXPLAIN 语法校验 → error?    │◄──────────────────┐
#            │                  │            └──────────────┬───────────────┘                   │
#            │                  │                           │                                   │
#            │                  │                           │────────┐error 且 fix_rounds=0      │回校验
#            │                  │                           │        ▼                          │
#            │                  │                           │  ┌──────────────────┐             │
#            │                  │                           │  │   correct_sql    │─────────────┘
#            │                  │                           │  │ 带错误重写（最多 1 次）│
#            │                  │                           │  └──────────────────┘
#            │                  │                           ▼  (通过)
#            │                  │            ┌──────────────────────────────┐
#            │                  │            │           run_sql            │
#            │                  │            │ 只返回 rows，不发 result 帧     │
#            │                  │            └──────────────┬───────────────┘
#            │                  │                           ▼
#            │                  │            ┌──────────────────────────────┐
#            │                  │            │        check_result          │  ✅ 7 条规则
#            │                  │            │ 空结果/全NULL/按天未按日期分组  │
#            │                  │            │ 极值口径/比例越界/时间过滤为空   │
#            │                  │            │ 时间条件打在非日期列上          │
#            │                  │            │ 判断日期列：column_info.type   │
#            │                  │            └──────────────┬───────────────┘
#            │                  │                           │
#            │                  │     可疑且 check_rounds<=2 ─┤
#            │                  │           │               │ 通过/次数用完
#            │                  │           ▼               ▼
#            │                  │   （回 correct_sql）  ┌──────────────────────────┐
#            │                  │                      │        write_cache       │
#            │                  │                      │ 可疑→跳过缓存              │
#            │                  │                      │ 审计 status=ok/suspect   │
#            │                  │                      │ 唯一出口：发 1 个 result 帧 │
#            │                  │                      └────────┬─────────────────┘
#            │                  │                               ▼
#            └──────────────────┴──────────────────────────►┌─────────┐
#                                                           │   END   │
#                                                           └─────────┘
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.ask_clarify import ask_clarify
from app.agent.nodes.check_result import check_result
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.rewrite_question import rewrite_question
from app.agent.nodes.run_sql import run_sql
from app.agent.nodes.validate_sql import validate_sql
from app.agent.nodes.write_cache import write_cache
from app.agent.question import active_question
from app.agent.state import Nl2SqlState

MAX_FIX_ROUNDS = 1
MAX_CHECK_ROUNDS = 2


async def check_cache(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """两层缓存：先精确（归一化后 hash），再语义（embedding 相似度）。"""
    runtime.stream_writer({"type": "progress", "step": "检查缓存", "status": "running"})
    ctx = runtime.context
    cache = ctx["cache_repo"]
    user_id = state["user_id"]
    dataset_id = state["dataset_id"]
    version = state.get("schema_version", 1)
    question = active_question(state)

    context_sig = state.get("context_sig", "")

    # ① 精确命中：归一化后完全一致（多轮带上下文指纹，避免同句不同义）
    sql = await cache.get_exact(user_id, dataset_id, version, question, context_sig)
    if sql:
        runtime.stream_writer({"type": "progress", "step": "检查缓存", "status": "success"})
        return {"sql": sql, "hit_cache": True, "cache_kind": "exact"}

    # ② 语义命中：换种说法也能复用（cosine ≥ 阈值）
    try:
        vector = await ctx["embedding"].aembed_query(question)
        hit = await cache.get_semantic(
            user_id, dataset_id, version, vector, context_sig, question
        )
    except Exception:  # noqa: BLE001 - 语义缓存失败就当未命中
        hit = None

    runtime.stream_writer({"type": "progress", "step": "检查缓存", "status": "success"})
    if hit:
        semantic_sql, score = hit
        runtime.stream_writer(
            {"type": "progress", "step": "语义缓存命中", "status": "success", "score": round(score, 3)}# 浮点数四舍五入到 3 位小数。
        )
        return {"sql": semantic_sql, "hit_cache": True, "cache_kind": "semantic"}

    return {"hit_cache": False, "cache_kind": "miss"}


def route_after_rewrite(state: Nl2SqlState) -> str:
    """信息不全就去反问，不生成 SQL。"""
    return "check_cache" if state.get("complete", True) else "ask_clarify"


def route_after_cache(state: Nl2SqlState) -> str:
    return "run_sql" if state.get("hit_cache") else "extract_keywords"


def route_after_validate(state: Nl2SqlState) -> str:
    if state.get("error") is None:
        return "run_sql"
    if state.get("fix_rounds", 0) >= MAX_FIX_ROUNDS:
        return "run_sql"          # 修不动了，交给执行暴露错误
    return "correct_sql"


def route_after_check(state: Nl2SqlState) -> str:
    if state.get("retry_reason") and state.get("check_rounds", 0) <= MAX_CHECK_ROUNDS:
        return "correct_sql"
    return "write_cache"


async def join_filters(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """汇聚点：等 filter_table 和 filter_metric 都完成后再往下走。

    没有这个屏障时，两个分支完成时机不同（一个调 LLM、一个直接返回），
    add_extra_context / generate_sql 会被触发两次，报
    INVALID_CONCURRENT_GRAPH_UPDATE（同一 step 并发写 error 等键）。
    """
    return {}


builder = StateGraph(state_schema=Nl2SqlState, context_schema=Nl2SqlContext)

builder.add_node("rewrite_question", rewrite_question)
builder.add_node("ask_clarify", ask_clarify)
builder.add_node("check_cache", check_cache)
builder.add_node("extract_keywords", extract_keywords)
builder.add_node("recall_column", recall_column)
builder.add_node("recall_value", recall_value)
builder.add_node("recall_metric", recall_metric)
builder.add_node("merge_retrieved_info", merge_retrieved_info)
builder.add_node("filter_table", filter_table)
builder.add_node("filter_metric", filter_metric)
builder.add_node("join_filters", join_filters)
builder.add_node("add_extra_context", add_extra_context)
builder.add_node("generate_sql", generate_sql)
builder.add_node("validate_sql", validate_sql)
builder.add_node("correct_sql", correct_sql)
builder.add_node("run_sql", run_sql)
builder.add_node("check_result", check_result)
builder.add_node("write_cache", write_cache)

builder.add_edge(START, "rewrite_question")
builder.add_conditional_edges(
    "rewrite_question",
    route_after_rewrite,
    {"check_cache": "check_cache", "ask_clarify": "ask_clarify"},
)
builder.add_edge("ask_clarify", END)
builder.add_conditional_edges(
    "check_cache",
    route_after_cache,
    {"run_sql": "run_sql", "extract_keywords": "extract_keywords"},
)
builder.add_edge("extract_keywords", "recall_column")
builder.add_edge("extract_keywords", "recall_value")
builder.add_edge("extract_keywords", "recall_metric")
builder.add_edge("recall_column", "merge_retrieved_info")
builder.add_edge("recall_value", "merge_retrieved_info")
builder.add_edge("recall_metric", "merge_retrieved_info")
builder.add_edge("merge_retrieved_info", "filter_table")
# 注意：这里必须是固定边。曾经试过"无指标时直接跳到 add_extra_context"，
# 但两个父节点（filter_table / merge）不同步完成，会让 add_extra_context
# 及其下游（generate_sql）跑两次，触发 LangGraph 的
# INVALID_CONCURRENT_GRAPH_UPDATE（error 键被并发写）。
# filter_metric 内部本来就在无指标时立即 return，不调 LLM。
builder.add_edge("merge_retrieved_info", "filter_metric")
# 列表形式的 add_edge = 汇聚屏障：等 filter_table 与 filter_metric 都完成
builder.add_edge(["filter_table", "filter_metric"], "join_filters")
builder.add_edge("join_filters", "add_extra_context")
builder.add_edge("add_extra_context", "generate_sql")
builder.add_edge("generate_sql", "validate_sql")
builder.add_conditional_edges(
    "validate_sql",
    route_after_validate,
    {"run_sql": "run_sql", "correct_sql": "correct_sql"},
)
builder.add_edge("correct_sql", "validate_sql")
builder.add_edge("run_sql", "check_result")
builder.add_conditional_edges(
    "check_result",
    route_after_check,
    {"correct_sql": "correct_sql", "write_cache": "write_cache"},
)
builder.add_edge("write_cache", END)

graph = builder.compile()
