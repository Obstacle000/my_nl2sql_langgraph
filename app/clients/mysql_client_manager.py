"""MySQL：全局 Engine + session 工厂，请求级 Session。"""


from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.conf.app_config import MySQLConfig, app_config


class MySQLClientManager:
    def __init__(self, config: MySQLConfig) -> None:
        self.config = config
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def _url(self, database: str | None = None) -> str:
        cfg = self.config
        db = database or cfg.database
        return (
            f"mysql+asyncmy://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{db}"
            "?charset=utf8mb4"
        )

    def init(self) -> None:
        self.engine = create_async_engine(
            self._url(), pool_size=10, max_overflow=10, pool_pre_ping=True
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


mysql_client_manager = MySQLClientManager(app_config.mysql)
