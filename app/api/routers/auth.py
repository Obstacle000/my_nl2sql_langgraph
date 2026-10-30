"""注册 / 登录（公开接口，不需要 CurrentUser）。"""

from fastapi import APIRouter

from app.api.deps import AuthServiceDep
from app.api.schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register(body: RegisterRequest, service: AuthServiceDep) -> dict:
    return await service.register(body.username, body.password)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, service: AuthServiceDep) -> TokenResponse:
    return TokenResponse(**await service.login(body.username, body.password))
