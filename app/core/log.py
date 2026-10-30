"""loguru 日志：自动注入 request_id 与 user_id。"""

import sys

from loguru import logger

from app.conf.app_config import app_config
from app.core.context import request_id_ctx_var, user_id_ctx_var

logger.remove()
logger = logger.patch(
    lambda record: record["extra"].update(
        request_id=request_id_ctx_var.get(), user_id=user_id_ctx_var.get()
    )
)
logger.add(
    sys.stdout,
    level=app_config.logging.level,
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <7}</level> | "
    "rid={extra[request_id]} uid={extra[user_id]} | <cyan>{name}</cyan> - <level>{message}</level>",
)
