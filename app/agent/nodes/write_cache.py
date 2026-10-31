"""执行成功后写缓存（精确 + 语义）与审计。

注意顺序：先把缓存和审计写完，最后再发 result 帧。
客户端拿到 result 就会断流，如果此时还在 commit，会触发
"close() while commit() in progress"，审计丢失。
"""

import time

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.question import active_question
from app.agent.state import Nl2SqlState
from app.core.log import logger


async def write_cache(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "写缓存", "status": "running"})
    ctx = runtime.context
    cache = ctx["cache_repo"]
    user_id = ctx["user_id"]
    dataset_id = ctx["dataset_id"]
    version = state.get("schema_version", 1)
    question = active_question(state)
    sql = state.get("sql", "")

    started = state.get("started_at") or time.time()
    # 自检最终未通过：结果可疑，不写缓存（避免错误答案被固化），只记审计
    suspect = state.get("retry_reason")
    context_sig = state.get("context_sig", "")
    if sql and not suspect:
        await cache.set_exact(user_id, dataset_id, version, question, sql, context_sig)
        try:
            vector = await ctx["embedding"].aembed_query(question)
            await cache.set_semantic(
                user_id, dataset_id, version, question, vector, sql, context_sig
            )
        except Exception as exc:  # noqa: BLE001 - 语义缓存失败不影响主流程
            logger.warning(f"语义缓存写入失败: {exc}")

    try:
        await ctx["history_repo"].add(
            user_id=user_id,
            dataset_id=dataset_id,
            question=question,
            sql=sql,
            hit_cache=bool(state.get("hit_cache")),
            rows_count=len(state.get("rows") or []),
            latency_ms=int((time.time() - started) * 1000),
            status="suspect" if suspect else "ok",
        )
    except Exception as exc:  # noqa: BLE001 - 审计失败不影响结果返回
        logger.warning(f"写审计失败: {exc}")

    # 统一出口：重试多次也只在这里发一次 result 帧（放最后，发完即可断流）
    runtime.stream_writer(
        {
            "type": "result",
            "data": state.get("rows") or [],
            "sql": sql,
            "hit_cache": bool(state.get("hit_cache")),
            "cache_kind": state.get("cache_kind", "miss"),
            "suspect_reason": suspect,
            "assumed": state.get("assumed") or None,
        }
    )
    runtime.stream_writer({"type": "progress", "step": "写缓存", "status": "success"})
    return {}
