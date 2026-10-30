"""最小可用图：缓存 → 召回 → 生成 → 校验 → 执行。"""

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


async def check_cache(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """命中缓存则直接填 sql，后续跳过生成。"""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "检查缓存", "status": "running"})
    cache = runtime.context["cache_repo"]
    sql = await cache.get_exact(
        state["user_id"], state["dataset_id"], state["schema_version"], state["question"]
    )
    writer({"type": "progress", "step": "检查缓存", "status": "success"})
    if sql:
        return {"sql": sql, "hit_cache": True}
    return {"hit_cache": False}


async def recall(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """占位：下一步接 Qdrant 字段召回 + ES 取值召回 + MySQL 指标。"""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回", "status": "running"})
    writer({"type": "progress", "step": "召回", "status": "success"})
    return {"candidates": []}


async def generate_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """占位：下一步接 prompt + LLM 生成 SQL。"""
    if state.get("sql"):
        return {}
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "生成SQL", "status": "running"})
    writer({"type": "progress", "step": "生成SQL", "status": "success"})
    return {"sql": ""}


async def validate_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """占位：下一步接 EXPLAIN 校验。"""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校验SQL", "status": "running"})
    writer({"type": "progress", "step": "校验SQL", "status": "success"})
    return {"error": None}


async def run_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    """占位：下一步接只读执行。"""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "执行SQL", "status": "running"})
    writer({"type": "progress", "step": "执行SQL", "status": "success"})
    writer({"type": "result", "data": []})
    return {"rows": []}


def route_after_cache(state: Nl2SqlState) -> str:
    return "run_sql" if state.get("hit_cache") else "recall"


builder = StateGraph(state_schema=Nl2SqlState, context_schema=Nl2SqlContext)
builder.add_node("check_cache", check_cache)
builder.add_node("recall", recall)
builder.add_node("generate_sql", generate_sql)
builder.add_node("validate_sql", validate_sql)
builder.add_node("run_sql", run_sql)

builder.add_edge(START, "check_cache")
builder.add_conditional_edges(
    "check_cache",
    route_after_cache,
    {"run_sql": "run_sql", "recall": "recall"},
)
builder.add_edge("recall", "generate_sql")
builder.add_edge("generate_sql", "validate_sql")
builder.add_edge("validate_sql", "run_sql")
builder.add_edge("run_sql", END)

graph = builder.compile()
