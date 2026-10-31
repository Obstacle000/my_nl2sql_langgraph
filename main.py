"""FastAPI 入口：第一层中间件（解析 + 续签，不拒绝）+ 路由注册。"""

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jwt import PyJWTError

from app.api.lifespan import lifespan
from app.api.routers import auth, conversations, datasets, datasources, metrics, query
from app.core.context import request_id_ctx_var, user_id_ctx_var
from app.core.errors import AppError
from app.core.log import logger
from app.core.security import create_access_token, decode_access_token

app = FastAPI(title="my-nl2sql", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """把业务异常翻译成 HTTP 状态码，而不是 500。"""
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
app.include_router(auth.router)          # 公开：不挂 CurrentUser
app.include_router(datasources.public_router)   # 公开：示例接口
app.include_router(datasources.router)
app.include_router(datasets.router)
app.include_router(metrics.router)
app.include_router(query.router)
app.include_router(conversations.router)

# token 剩余不足这么久就续签（滑动续期）
REFRESH_THRESHOLD_S = 15 * 60


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """第一层：解析 token → ContextVar；快过期则续签。

    这一层永不拒绝请求：是否允许访问由第二层（每个路由的 user_id: CurrentUser）决定，
    这样公开接口也能在带 token 时享受续签。
    """
    request_id_ctx_var.set(uuid.uuid4().hex[:8])
    user_id_ctx_var.set(None)
    new_token: str | None = None

    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_access_token(auth.removeprefix("Bearer ").strip())
            user_id_ctx_var.set(int(payload["sub"]))
            if int(payload["exp"]) - int(time.time()) < REFRESH_THRESHOLD_S:
                new_token = create_access_token(int(payload["sub"]), payload["username"])
        except (PyJWTError, KeyError, ValueError) as exc:
            # 解析失败按未登录处理，不在这里拒绝
            logger.debug(f"token 解析失败，按未登录处理: {exc}")

    response = await call_next(request)
    if new_token is not None:
        response.headers["X-New-Token"] = new_token
        response.headers["Access-Control-Expose-Headers"] = "X-New-Token"
    return response
