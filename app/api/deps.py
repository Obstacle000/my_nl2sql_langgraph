"""依赖注入：Session、Repository、Service、当前用户。

约定：
  · 这里只做"装配"，不带 user_id 等运行期参数（那些由路由传给服务方法）
  · 仓储 / 服务的依赖别名集中在文件末尾，路由只 import 别名
"""

from pathlib import Path
from typing import Annotated

from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.redis_client_manager import redis_client_manager
from app.conf.app_config import app_config
from app.core.context import user_id_ctx_var
from app.core.errors import UnauthorizedError
from app.datasources.registry import DataSourceRegistry
from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.conversation_repo import ConversationRepository
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.datasource_repo import DataSourceRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.repositories.mysql.user_repo import UserRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository
from app.repositories.redis.sql_cache_repo import SQLCacheRepository
from app.services.auth_service import AuthService
from app.services.dataset_service import DatasetService
from app.services.datasource_service import DatasourceService
from app.services.meta_index_service import MetaIndexService
from app.services.metric_service import MetricService

UPLOAD_DIR = Path("data/uploads")

# 进程内单例：持有 manager，session_factory 在 lifespan init() 之后才可用
_registry = DataSourceRegistry(mysql_client_manager)


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


# ---------------- 仓储 ----------------


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


def get_dataset_repository(session: SessionDep) -> DatasetRepository:
    return DatasetRepository(session)


def get_conversation_repository(session: SessionDep) -> ConversationRepository:
    return ConversationRepository(session)


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


# ---------------- 仓储依赖别名 ----------------

DatasetRepositoryDep = Annotated[DatasetRepository, Depends(get_dataset_repository)]
MetaRepositoryDep = Annotated[MetaRepository, Depends(get_meta_repository)]
ConversationRepositoryDep = Annotated[
    ConversationRepository, Depends(get_conversation_repository)
]
QdrantRepositoryDep = Annotated[MetaQdrantRepository, Depends(get_qdrant_repository)]
ValueESRepositoryDep = Annotated[ValueESRepository, Depends(get_value_es_repository)]
SQLCacheRepositoryDep = Annotated[SQLCacheRepository, Depends(get_sql_cache_repository)]
DatasourceRegistryDep = Annotated[DataSourceRegistry, Depends(get_datasource_registry)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


# ---------------- 服务装配 ----------------


def get_auth_service(user_repo: UserRepositoryDep) -> AuthService:
    return AuthService(user_repo)


def get_meta_index_service(
    meta_repo: MetaRepositoryDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
) -> MetaIndexService:
    return MetaIndexService(qdrant, es, meta_repo)


MetaIndexServiceDep = Annotated[MetaIndexService, Depends(get_meta_index_service)]


def get_dataset_service(
    session: SessionDep,
    dataset_repo: DatasetRepositoryDep,
    meta_repo: MetaRepositoryDep,
    index_service: MetaIndexServiceDep,
    registry: DatasourceRegistryDep,
) -> DatasetService:
    return DatasetService(
        dataset_repo=dataset_repo,
        meta_repo=meta_repo,
        physical_repo=PhysicalTableRepository(session),
        index_service=index_service,
        registry=registry,
        upload_dir=UPLOAD_DIR,
    )


def get_datasource_service(
    session: SessionDep,
    meta_repo: MetaRepositoryDep,
    index_service: MetaIndexServiceDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
) -> DatasourceService:
    return DatasourceService(
        datasource_repo=DataSourceRepository(session),
        dataset_repo=DatasetRepository(session),
        meta_repo=meta_repo,
        physical_repo=PhysicalTableRepository(session),
        index_service=index_service,
        qdrant=qdrant,
        es=es,
    )


def get_metric_service(
    session: SessionDep,
    meta_repo: MetaRepositoryDep,
    index_service: MetaIndexServiceDep,
) -> MetricService:
    return MetricService(
        dataset_repo=DatasetRepository(session),
        meta_repo=meta_repo,
        index_service=index_service,
    )


# ---------------- 服务依赖别名 ----------------

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]
DatasourceServiceDep = Annotated[DatasourceService, Depends(get_datasource_service)]
MetricServiceDep = Annotated[MetricService, Depends(get_metric_service)]
