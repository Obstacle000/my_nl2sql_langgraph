"""问数接口（SSE）。"""

import json
import time

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
    SessionDep,
    SQLCacheRepositoryDep,
    ValueESRepositoryDep,
)
from app.api.schemas import QueryRequest
from app.clients.embedding_client_manager import embedding_client_manager
from app.core.errors import NotFoundError
from app.repositories.mysql.history_repo import HistoryRepository

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query")
async def query(
    body: QueryRequest,
    user_id: CurrentUser,
    session: SessionDep,
    dataset_repo: DatasetRepositoryDep,
    meta: MetaRepositoryDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
    cache: SQLCacheRepositoryDep,
    registry: DatasourceRegistryDep,
) -> StreamingResponse:
    dataset = await dataset_repo.get(user_id, body.dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")

    source = await registry.get(user_id, body.dataset_id)

    context = Nl2SqlContext(
        user_id=user_id,
        dataset_id=body.dataset_id,
        datasource_id=dataset.datasource_id or 0,
        dataset_name=dataset.name,
        source=source,
        embedding=embedding_client_manager.client,
        meta_repo=meta,
        qdrant_repo=qdrant,
        es_repo=es,
        cache_repo=cache,
        history_repo=HistoryRepository(session),
    )
    state = Nl2SqlState(
        question=body.question,
        user_id=user_id,
        dataset_id=body.dataset_id,
        schema_version=dataset.schema_version,
        fix_rounds=0,
        check_rounds=0,
        hit_cache=False,
        _started_at=time.time(),
    )

    async def stream():
        try:
            async for chunk in graph.astream(state, context=context, stream_mode="custom"):
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 统一包成 error 帧
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
