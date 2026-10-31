"""数据源接口：服务由仓储装配而来。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    CurrentUser,
    DatasourceRegistryDep,
    QdrantRepositoryDep,
    SessionDep,
    ValueESRepositoryDep,
)
from app.api.schemas import (
    DataSourceCreateRequest,
    DataSourceProbeRequest,
    DataSourceUpdateRequest,
    SyncRequest,
)
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.datasource_repo import DataSourceRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.services.datasource_service import DatasourceService
from app.services.meta_index_service import MetaIndexService

router = APIRouter(prefix="/api/datasources", tags=["datasources"])

# 公开路由：不挂 CurrentUser，匿名可访问
public_router = APIRouter(
    prefix="/api/datasources/public",
    tags=["datasources-public"],
)


@public_router.get("/templates")
async def list_templates() -> dict:
    """示例：不需要登录的接口。"""
    return {"templates": [{"name": "订单模板"}, {"name": "会员模板"}]}


def get_datasource_service(
    session: SessionDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
) -> DatasourceService:
    meta_repo = MetaRepository(session)
    return DatasourceService(
        datasource_repo=DataSourceRepository(session),
        dataset_repo=DatasetRepository(session),
        meta_repo=meta_repo,
        physical_repo=PhysicalTableRepository(session),
        index_service=MetaIndexService(qdrant, es, meta_repo),
        qdrant=qdrant,
        es=es,
    )


DatasourceServiceDep = Annotated[DatasourceService, Depends(get_datasource_service)]


@router.post("/probe")
async def probe(
    body: DataSourceProbeRequest,
    user_id: CurrentUser,
    service: DatasourceServiceDep,
) -> dict:
    """只测试连接并返回表清单，不落库。"""
    return await service.probe(body.config.model_dump())


@router.post("", status_code=201)
async def create(
    body: DataSourceCreateRequest,
    user_id: CurrentUser,
    session: SessionDep,
    service: DatasourceServiceDep,
) -> dict:
    """创建数据源 + 数据集（只登记选中的表），并建索引。"""
    async with session.begin():
        return await service.create_mysql(
            user_id=user_id,
            name=body.name,
            config=body.config.model_dump(),
            dataset_name=body.dataset.name,
            dataset_description=body.dataset.description,
            tables=body.dataset.tables,
        )


@router.get("")
async def list_datasources(user_id: CurrentUser, service: DatasourceServiceDep) -> dict:
    return {"datasources": await service.list_datasources(user_id)}


@router.put("/{datasource_id}")
async def update_datasource(
    datasource_id: int,
    body: DataSourceUpdateRequest,
    user_id: CurrentUser,
    session: SessionDep,
    service: DatasourceServiceDep,
    registry: DatasourceRegistryDep,
) -> dict:
    """改名字或连接配置；传了 config 会先测连接。"""
    async with session.begin():
        result = await service.update(
            user_id,
            datasource_id,
            name=body.name,
            config=body.config.model_dump() if body.config else None,
        )
    if body.config is not None:
        # 配置变了，踢掉进程内缓存的连接池，避免继续用旧引擎
        await registry.invalidate(user_id, datasource_id)
    return result


@router.post("/{datasource_id}/test")
async def test_connection(
    datasource_id: int, user_id: CurrentUser, service: DatasourceServiceDep
) -> dict:
    return await service.test(user_id, datasource_id)


@router.post("/{datasource_id}/sync/preview")
async def preview_sync(
    datasource_id: int, user_id: CurrentUser, service: DatasourceServiceDep
) -> dict:
    """第一步：只读预览，返回新增/已有的表，供前端勾选。"""
    return await service.preview_sync(user_id, datasource_id)


@router.post("/{datasource_id}/sync")
async def sync_schema(
    datasource_id: int,
    user_id: CurrentUser,
    session: SessionDep,
    service: DatasourceServiceDep,
    body: SyncRequest | None = None,
) -> dict:
    """第二步：按勾选新增表（body 为空则加全部新增表）。"""
    tables = body.tables if body else None
    drop_columns = body.drop_columns if body else False
    drop_tables = body.drop_tables if body else False
    async with session.begin():
        return await service.sync(user_id, datasource_id, tables, drop_columns, drop_tables)


@router.delete("/{datasource_id}")
async def delete_datasource(
    datasource_id: int,
    user_id: CurrentUser,
    session: SessionDep,
    service: DatasourceServiceDep,
    registry: DatasourceRegistryDep,
) -> dict:
    async with session.begin():
        result = await service.delete(user_id, datasource_id)
    # 删完把进程内缓存的连接池一起释放，避免"删了还在用旧引擎"
    await registry.invalidate(user_id, datasource_id)
    return result
