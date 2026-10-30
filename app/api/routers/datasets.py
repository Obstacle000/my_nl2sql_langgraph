"""数据集接口：服务由仓储装配而来。"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import (
    CurrentUser,
    DatasetRepositoryDep,
    QdrantRepositoryDep,
    SessionDep,
    ValueESRepositoryDep,
)
from app.api.schemas import DatasetCreateRequest, DatasetCreateResponse, TableCreateResponse
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.services.dataset_service import DatasetService
from app.services.meta_index_service import MetaIndexService

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

UPLOAD_DIR = Path("data/uploads")


def get_dataset_service(
    session: SessionDep,
    dataset_repo: DatasetRepositoryDep,
    qdrant: QdrantRepositoryDep,
    es: ValueESRepositoryDep,
) -> DatasetService:
    meta_repo = MetaRepository(session)
    return DatasetService(
        dataset_repo=dataset_repo,
        meta_repo=meta_repo,
        physical_repo=PhysicalTableRepository(session),
        index_service=MetaIndexService(qdrant, es, meta_repo),
        upload_dir=UPLOAD_DIR,
    )


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]


@router.get("")
async def list_datasets(user_id: CurrentUser, repo: DatasetRepositoryDep) -> dict:
    """当前用户的数据集列表（只返回自己的）。"""
    rows = await repo.list_by_user(user_id)
    return {
        "datasets": [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "datasource_id": row.datasource_id,
                "schema_version": row.schema_version,
            }
            for row in rows
        ]
    }


@router.post("", status_code=201, response_model=DatasetCreateResponse)
async def create_dataset(
    body: DatasetCreateRequest, user_id: CurrentUser, service: DatasetServiceDep
) -> DatasetCreateResponse:
    """新建空数据集（同时建一个 kind=csv 的数据源）。"""
    result = await service.create_dataset(
        user_id=user_id, name=body.name, description=body.description
    )
    return DatasetCreateResponse(**result)


@router.post("/{dataset_id}/tables", status_code=201, response_model=TableCreateResponse)
async def upload_csv(
    dataset_id: int,
    user_id: CurrentUser,
    service: DatasetServiceDep,
    name: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008
) -> TableCreateResponse:
    """往数据集里追加一张表（CSV → 物理表 + 元数据 + 索引）。"""
    raw = await file.read()
    result = await service.add_csv_table(
        user_id=user_id,
        dataset_id=dataset_id,
        table_name=name,
        csv_bytes=raw,
        filename=file.filename or "data.csv",
    )
    return TableCreateResponse(**result)
