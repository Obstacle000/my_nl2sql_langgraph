"""Qdrant：字段/指标向量检索。"""


from qdrant_client import AsyncQdrantClient

from app.conf.app_config import QdrantConfig, app_config


class QdrantClientManager:
    def __init__(self, config: QdrantConfig) -> None:
        self.config = config
        self.client: AsyncQdrantClient | None = None

    def init(self) -> None:
        self.client = AsyncQdrantClient(
            url=f"http://{self.config.host}:{self.config.port}"
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()


qdrant_client_manager = QdrantClientManager(app_config.qdrant)
