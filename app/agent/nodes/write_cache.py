"""执行成功后写缓存（精确 + 语义）与审计。"""

import time

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState
from app.core.log import logger


async def write_cache(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "写缓存", "status": "running"})
    ctx = runtime.context
    cache = ctx["cache_repo"]
    user_id = ctx["user_id"]
    dataset_id = ctx["dataset_id"]
    version = state.get("schema_version", 1)
    question = state["question"]
    sql = state.get("sql", "")

    started = state.get("started_at") or time.time()
    if sql:
        await cache.set_exact(user_id, dataset_id, version, question, sql)
        try:
            vector = await ctx["embedding"].aembed_query(question)
            await cache.set_semantic(user_id, dataset_id, version, question, vector, sql)
        except Exception as exc:  # noqa: BLE001 - 语义缓存失败不影响主流程
            logger.warning(f"语义缓存写入失败: {exc}")

    await ctx["history_repo"].add(
        user_id=user_id,
        dataset_id=dataset_id,
        question=question,
        sql=sql,
        hit_cache=bool(state.get("hit_cache")),
        rows_count=len(state.get("rows") or []),
        latency_ms=int((time.time() - started) * 1000),
        status="ok",
    )
    runtime.stream_writer({"type": "progress", "step": "写缓存", "status": "success"})
    return {}
