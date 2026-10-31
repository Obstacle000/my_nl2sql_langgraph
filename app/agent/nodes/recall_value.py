"""取值召回：关键词 → ES 全文（带租户过滤）。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


async def recall_value(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "召回收值", "status": "running"})
    ctx = runtime.context
    es = ctx["es_repo"]

    question = state.get("question", "")
    found: dict[str, dict] = {}
    for keyword in state["keywords"]:
        hits = await es.search(
            keyword,
            user_id=ctx["user_id"],
            dataset_id=ctx["dataset_id"],
            limit=10,
            min_score=0.6,
        )
        for hit in hits:
            # 只保留"真的出现在问题里"的值：
            # ES 是模糊匹配，不校验会让模型凭空加 WHERE 条件
            value = str(hit.get("value", ""))
            if value and value in question:
                found.setdefault(hit["id"], hit)

    runtime.stream_writer({"type": "progress", "step": "召回收值", "status": "success"})
    return {"retrieved_value_infos": list(found.values())}
