"""字段召回：关键词向量 → Qdrant（带租户过滤）→ 按 payload.id 去重。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState

COLLECTION = "column_info_collection"


async def recall_column(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "召回字段", "status": "running"})
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
            limit=10,
            score_threshold=0.5,
        )
        for hit in hits:
            # dict.setdefault(key, default)：key 存在就返回它的值；不存在就插入 default 并返回它。
            # hit是一个字典,是point里的payload,也就是colomn_info
            found.setdefault(hit["id"], hit)

    runtime.stream_writer({"type": "progress", "step": "召回字段", "status": "success"})
    return {"retrieved_column_infos": list(found.values())}
