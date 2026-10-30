"""指标召回：关键词向量 → Qdrant。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState

COLLECTION = "metric_info_collection"


async def recall_metric(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "召回指标", "status": "running"})
    ctx = runtime.context
    embedder = ctx["embedding"]
    qdrant = ctx["qdrant_repo"]

    found: dict[str, dict] = {}
    for keyword in state["keywords"]:
        vector = await embedder.aembed_query(keyword)
        hits = await qdrant.search(
            COLLECTION,
            vector,
            user_id=ctx["user_id"],
            dataset_id=ctx["dataset_id"],
            limit=5,
            score_threshold=0.5,
        )
        for hit in hits:
            found.setdefault(hit["id"], hit)

    runtime.stream_writer({"type": "progress", "step": "召回指标", "status": "success"})
    return {"retrieved_metric_infos": list(found.values())}
