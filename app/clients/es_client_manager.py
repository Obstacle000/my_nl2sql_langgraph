"""Elasticsearch：字段取值全文检索。"""


from elasticsearch import AsyncElasticsearch

from app.conf.app_config import ESConfig, app_config


class ESClientManager:
    def __init__(self, config: ESConfig) -> None:
        self.config = config
        self.client: AsyncElasticsearch | None = None

    def init(self) -> None:
        # 用 URL 字符串最省事：host 字典在部分版本要求额外提供 scheme
        self.client = AsyncElasticsearch(
            hosts=[f"http://{self.config.host}:{self.config.port}"]
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()


es_client_manager = ESClientManager(app_config.elasticsearch)
