"""密码哈希与 JWT。"""

import datetime as dt
from typing import Any

import jwt
from passlib.context import CryptContext

from app.conf.app_config import app_config
from app.core.errors import UnauthorizedError

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


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
