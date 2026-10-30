"""注册 / 登录：只依赖仓储。"""

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.mysql.user_repo import UserRepository


class AuthService:
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def register(self, username: str, password: str) -> dict[str, str]:
        if await self.user_repo.get_by_username(username) is not None:
            raise ConflictError("用户名已存在")
        await self.user_repo.create_committed(username, hash_password(password))
        return {"username": username}

    async def login(self, username: str, password: str) -> dict[str, str]:
        user = await self.user_repo.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("用户名或密码错误")
        return {
            "access_token": create_access_token(user.id, user.username),
            "token_type": "bearer",
        }
