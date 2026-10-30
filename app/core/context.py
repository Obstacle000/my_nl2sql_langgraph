"""请求上下文：request_id / user_id 用 ContextVar 隔离并发请求。

注意：asyncio 里不能用 threading.local（同一线程跑多个协程会串数据）。
"""

from contextvars import ContextVar

request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx_var: ContextVar[int | None] = ContextVar("user_id", default=None)
