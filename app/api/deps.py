"""依赖注入：Session、Repository、Service、当前用户。"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.mysql_client_manager import mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.conf.app_config import app_config
from app.core.context import user_id_ctx_var
from app.core.errors import UnauthorizedError
from app.datasources.registry import DataSourceRegistry
from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.user_repo import UserRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository
from app.repositories.redis.sql_cache_repo import SQLCacheRepository
from app.services.auth_service import AuthService

# 进程内单例：持有 manager，session_factory 在 lifespan init() 之后才可用
_registry = DataSourceRegistry(mysql_client_manager)
from elasticsearch import AsyncElasticsearch

from app.clients.es_client_manager import es_client_manager


def get_es_client() -> AsyncElasticsearch:
    if es_client_manager.client is None:
        es_client_manager.init()
    return es_client_manager.client

async def get_session():
    """请求级 Session。"""
    async with mysql_client_manager.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_current_user_id() -> int:
    """第二层：从第一层写入的 ContextVar 读 user_id；为空即未登录。"""
    user_id = user_id_ctx_var.get()
    if user_id is None:
        raise UnauthorizedError("登录已失效，请重新登录")
    return user_id


CurrentUser = Annotated[int, Depends(get_current_user_id)]


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


def get_auth_service(
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> AuthService:
    return AuthService(user_repo)


def get_dataset_repository(session: SessionDep) -> DatasetRepository:
    return DatasetRepository(session)


def get_meta_repository(session: SessionDep) -> MetaRepository:
    return MetaRepository(session)


def get_qdrant_repository() -> MetaQdrantRepository:
    return MetaQdrantRepository(qdrant_client_manager.client, app_config.qdrant.embedding_size)


def get_value_es_repository() -> ValueESRepository:
    return ValueESRepository(get_es_client())


def get_datasource_registry() -> "DataSourceRegistry":
    """数据源注册表：进程内单例，池子做 LRU 上限。"""
    return _registry


def get_sql_cache_repository() -> SQLCacheRepository:
    return SQLCacheRepository(redis_client_manager.client, app_config.cache)


# ---- 依赖类型别名：路由里只用这些名字，写起来短、类型也有提示 ----

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_dataset_repository)]
MetaRepositoryDep = Annotated[MetaRepository, Depends(get_meta_repository)]
QdrantRepositoryDep = Annotated[MetaQdrantRepository, Depends(get_qdrant_repository)]
ValueESRepositoryDep = Annotated[ValueESRepository, Depends(get_value_es_repository)]
SQLCacheRepositoryDep = Annotated[SQLCacheRepository, Depends(get_sql_cache_repository)]
DatasourceRegistryDep = Annotated[DataSourceRegistry, Depends(get_datasource_registry)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
