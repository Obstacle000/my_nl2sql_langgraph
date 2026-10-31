"""启动时初始化客户端，关闭时释放（含索引巡检后台任务）。"""

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.conf.app_config import app_config
from app.core.log import logger
from app.models import Base
from app.services.index_janitor import sweep

JANITOR_INTERVAL_SECONDS = 6 * 3600      # 每 6 小时扫一次
JANITOR_FIRST_DELAY_SECONDS = 60         # 启动后 1 分钟先跑一次


async def _janitor_loop() -> None:
    """后台索引巡检：删掉"数据集已不存在"的孤儿向量。"""
    await asyncio.sleep(JANITOR_FIRST_DELAY_SECONDS)
    url = f"http://{app_config.qdrant.host}:{app_config.qdrant.port}"
    while True:
        try:
            await sweep(mysql_client_manager.session_factory, url)
        except Exception as exc:  # noqa: BLE001 - 巡检失败不能影响主服务
            logger.warning(f"索引巡检异常：{exc}")
        await asyncio.sleep(JANITOR_INTERVAL_SECONDS)


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

    # 索引巡检：默认开启；设 INDEX_JANITOR=0 可关闭
    janitor_task = None
    if os.getenv("INDEX_JANITOR", "1") != "0":
        janitor_task = asyncio.create_task(_janitor_loop())

    yield

    if janitor_task is not None:
        janitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await janitor_task

    await qdrant_client_manager.close()
    await es_client_manager.close()
    await redis_client_manager.close()
    await mysql_client_manager.close()
