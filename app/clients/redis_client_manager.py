"""Redis：全局连接池。"""


from redis.asyncio import Redis

from app.conf.app_config import RedisConfig, app_config


class RedisClientManager:
    def __init__(self, config: RedisConfig) -> None:
        self.config = config
        self.client: Redis | None = None

    def init(self) -> None:
        self.client = Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password or None,
            decode_responses=True,
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()


redis_client_manager = RedisClientManager(app_config.redis)
