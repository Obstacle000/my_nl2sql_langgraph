"""问数接口（SSE）：全部使用 Annotated 依赖。"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.context import Nl2SqlContext
from app.agent.graph import graph
from app.agent.state import Nl2SqlState
from app.api.deps import (
    CurrentUser,
    DatasetRepositoryDep,
    DatasourceRegistryDep,
    MetaRepositoryDep,
    QdrantRepositoryDep,
    SQLCacheRepositoryDep,
    ValueESRepositoryDep,
)
from app.api.schemas import QueryRequest
from app.core.errors import NotFoundError

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query")
async def query(
    body: QueryRequest,
    user_id: CurrentUser,
    dataset_repo: DatasetRepositoryDep,
    meta: MetaRepositoryDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
    cache: SQLCacheRepositoryDep,
    registry: DatasourceRegistryDep,
) -> StreamingResponse:
    # ① 数据集必须属于当前用户（越权统一 404）
    dataset = await dataset_repo.get(user_id, body.dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")

    # ② 按数据集取数据源（CSV 或 MySQL），执行与 schema 都走它
    source = await registry.get(user_id, body.dataset_id)

    context = Nl2SqlContext(
        user_id=user_id,
        dataset_id=body.dataset_id,
        source=source,
        meta_repo=meta,
        qdrant_repo=qdrant,
        es_repo=es,
        cache_repo=cache,
        sql_executor=source,
    )
    state = Nl2SqlState(
        question=body.question,
        user_id=user_id,
        dataset_id=body.dataset_id,
        schema_version=dataset.schema_version,
    )

    async def stream():
        try:
            async for chunk in graph.astream(state, context=context, stream_mode="custom"):
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
