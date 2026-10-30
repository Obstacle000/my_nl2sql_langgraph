"""运行上下文：只放依赖对象（不进检查点、不可序列化也没关系）。"""

from typing import TypedDict

from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository
from app.repositories.redis.sql_cache_repo import SQLCacheRepository


class Nl2SqlContext(TypedDict):
    user_id: int
    dataset_id: int
    source: object  # DataSource：执行/发现 schema 都走它
    meta_repo: MetaRepository
    qdrant_repo: MetaQdrantRepository
    es_repo: ValueESRepository
    cache_repo: SQLCacheRepository
    sql_executor: object  # 只读执行器（下一步实现）
