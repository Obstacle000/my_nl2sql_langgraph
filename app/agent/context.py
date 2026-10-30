"""运行上下文：只放依赖对象，不进检查点。"""

from typing import TypedDict

from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.history_repo import HistoryRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository
from app.repositories.redis.sql_cache_repo import SQLCacheRepository


class Nl2SqlContext(TypedDict):
    user_id: int
    dataset_id: int
    datasource_id: int
    dataset_name: str
    source: object                 # DataSource 实例
    embedding: object              # OpenAIEmbeddings
    meta_repo: MetaRepository
    qdrant_repo: MetaQdrantRepository
    es_repo: ValueESRepository
    cache_repo: SQLCacheRepository
    history_repo: HistoryRepository
