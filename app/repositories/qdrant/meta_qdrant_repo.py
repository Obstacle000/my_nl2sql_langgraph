"""Qdrant：字段 / 指标向量。

多租户关键：payload 带 user_id + dataset_id，检索必须 filter。
"""

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.entities.meta import ColumnInfoEntity, MetricInfoEntity


class MetaQdrantRepository:
    def __init__(self, client: AsyncQdrantClient, dim: int) -> None:
        self.client = client
        self.dim = dim

    async def ensure_collection(self, name: str) -> None:
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=self.dim, distance=models.Distance.COSINE
                ),
            )

    async def upsert(
        self, name: str, points: list[tuple[str, str, dict[str, Any]]]
    ) -> None:
        """points: (embedding_text, vector_id, payload) 由调用方算好向量。"""
        raise NotImplementedError("向量由 service 计算后调用 upsert_vectors")

    async def upsert_vectors(
        self, name: str, vectors: list[list[float]], payloads: list[dict[str, Any]]
    ) -> None:
        await self.ensure_collection(name)
        await self.client.upsert(
            collection_name=name,
            points=[
                models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
                for v, p in zip(vectors, payloads)
            ],
        )

    def _filter(self, user_id: int, dataset_id: int) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset_id)),
            ]
        )

    async def search(
        self,
        name: str,
        query_vector: list[float],
        *,
        user_id: int,
        dataset_id: int,
        limit: int = 20,
        score_threshold: float = 0.6,
    ) -> list[dict[str, Any]]:
        result = await self.client.query_points(
            collection_name=name,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=self._filter(user_id, dataset_id),
        )
        return [point.payload or {} for point in result.points]

    async def delete_by_dataset(self, name: str, user_id: int, dataset_id: int) -> None:
        """删除某数据集的全部向量（删数据源时用）。"""
        await self.client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(filter=self._filter(user_id, dataset_id)),
        )

    @staticmethod
    def column_payload(
        column: ColumnInfoEntity, user_id: int, dataset_id: int, datasource_id: int = 0
    ) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "dataset_id": dataset_id,
            "datasource_id": datasource_id,
            "id": column.id,
            "table_id": column.table_id,
            "name": column.name,
            "type": column.type,
            "role": column.role,
            "description": column.description,
            "examples": column.examples,
            "alias": column.alias,
        }

    @staticmethod
    def metric_payload(
        metric: MetricInfoEntity, user_id: int, dataset_id: int, datasource_id: int = 0
    ) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "dataset_id": dataset_id,
            "datasource_id": datasource_id,
            "id": metric.id,
            "name": metric.name,
            "description": metric.description,
            "expression": metric.expression,
            "relevant_columns": metric.relevant_columns,
            "alias": metric.alias,
        }
