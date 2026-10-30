"""密码哈希与 JWT。"""

import datetime as dt
from typing import Any

import bcrypt
import jwt

from app.conf.app_config import app_config
from app.core.errors import UnauthorizedError


def hash_password(raw: str) -> str:
    """bcrypt 直接调用：passlib 1.7 与 bcrypt>=4.1 不兼容。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, username: str) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + dt.timedelta(minutes=app_config.auth.access_token_minutes),
    }
    return jwt.encode(payload, app_config.auth.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, app_config.auth.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("登录已失效，请重新登录") from exc
