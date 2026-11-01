"""问数接口（SSE）。"""

import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.context import Nl2SqlContext
from app.agent.graph import graph
from app.agent.state import Nl2SqlState
from app.api.deps import (
    ConversationRepositoryDep,
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
from app.clients.mysql_client_manager import mysql_client_manager
from app.core.errors import NotFoundError
from app.repositories.mysql.conversation_repo import ConversationRepository
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
    conversation_repo: ConversationRepositoryDep,
) -> StreamingResponse:
    dataset = await dataset_repo.get(user_id, body.dataset_id)
    if dataset is None:
        raise NotFoundError("数据集不存在")

    history: list[dict] = []
    clarify_rounds = 0
    last_clarify = ""
    if body.conversation_id:
        conversation = await conversation_repo.get(user_id, body.conversation_id)
        if conversation is None:
            raise NotFoundError("会话不存在")
        if conversation.dataset_id != body.dataset_id:
            raise NotFoundError("会话与数据集不匹配")
        # 只取"成功问答轮"，跳过 clarify/error（避免把澄清语和半截问题带进上下文）
        pairs = await conversation_repo.recent_dialogue(body.conversation_id, turns=3)
        history = []
        for user_msg, assistant_msg in pairs:
            history.append({"role": "user", "content": user_msg.content, "sql": ""})
            history.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.rewritten or assistant_msg.content,
                    "sql": assistant_msg.sql,
                }
            )
        # 最近一次反问单独传给改写节点（不塞进 history，避免被抄进问题）
        last_clarify_row = await conversation_repo.last_clarify(body.conversation_id)
        last_clarify = last_clarify_row.content if last_clarify_row is not None else ""
        clarify_rounds = await conversation_repo.count_clarify(body.conversation_id)

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
        started_at=time.time(),
        conversation_id=body.conversation_id,
        history=history,
        clarify_rounds=clarify_rounds,
        last_clarify=last_clarify,
    )

    async def stream():
        started = time.time()
        final = {"sql": "", "rewritten": "", "msg_type": "error", "content": ""}
        try:
            async for chunk in graph.astream(state, context=context, stream_mode="custom"):
                kind = chunk.get("type")
                if kind == "rewritten":
                    final["rewritten"] = chunk.get("question", "")
                elif kind == "clarify":
                    final["msg_type"] = "clarify"
                    final["content"] = chunk.get("message", "")
                elif kind == "result":
                    final["msg_type"] = "sql"
                    final["sql"] = chunk.get("sql", "")
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 统一包成 error 帧
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            if body.conversation_id:
                await _save_turn(body, final, started)

    async def _save_turn(body: QueryRequest, final: dict, started: float) -> None:
        """独立短事务写消息：客户端断流也不会丢，失败不影响已推送的帧。"""
        factory = mysql_client_manager.session_factory
        if factory is None:
            return
        try:
            async with factory() as save_session:
                repo = ConversationRepository(save_session)
                await repo.add_message(
                    body.conversation_id, role="user", content=body.question, msg_type="ask"
                )
                await repo.add_message(
                    body.conversation_id,
                    role="assistant",
                    content=final.get("content", ""),
                    sql=final.get("sql", ""),
                    rewritten=final.get("rewritten", ""),
                    msg_type=final.get("msg_type", "error"),
                    latency_ms=int((time.time() - started) * 1000),
                )
                await save_session.commit()
        except Exception as exc:  # noqa: BLE001 - 落库失败只记日志
            from app.core.log import logger

            logger.warning(f"写会话消息失败: {exc}")

    return StreamingResponse(stream(), media_type="text/event-stream")
