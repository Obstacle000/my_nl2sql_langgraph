"""启动时初始化客户端，关闭时释放。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    mysql_client_manager.init()
    redis_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    embedding_client_manager.init()

    # 建表（生产环境应换成 alembic 迁移）
    async with mysql_client_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("SELECT 1"))

    yield

    await qdrant_client_manager.close()
    await es_client_manager.close()
    await redis_client_manager.close()
    await mysql_client_manager.close()
