"""凭证加密：Fernet（密钥来自环境变量 DS_SECRET_KEY）。"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    raw = os.environ.get("DS_SECRET_KEY", "")
    if not raw:
        raise RuntimeError("缺少环境变量 DS_SECRET_KEY（用于加密数据源凭证）")
    # 允许用户随便填一串：sha256 派生 32 字节，再 base64
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_json(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_json(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
