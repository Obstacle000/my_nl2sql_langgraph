"""把元数据写进 Qdrant（语义）与 ES（取值全文）。

重要约定：索引数据一律从 MySQL 读出，不直接吃内存实体，
这样 MySQL 是唯一事实源，索引随时可以重建。
"""

from app.clients.embedding_client_manager import embedding_client_manager
from app.entities.meta import ColumnInfoEntity
from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository


class MetaIndexService:
    COLUMN_COLLECTION = "column_info_collection"
    METRIC_COLLECTION = "metric_info_collection"

    def __init__(
        self,
        qdrant: MetaQdrantRepository,
        es: ValueESRepository,
        meta_repo: MetaRepository,
    ) -> None:
        self.qdrant = qdrant
        self.es = es
        self.meta_repo = meta_repo

    async def reindex_dataset(
        self, user_id: int, dataset_id: int, datasource_id: int = 0
    ) -> int:
        """从 MySQL 读字段，重建该数据集的 Qdrant 向量与 ES 取值索引。"""
        # 先删该数据集旧向量，避免重复 reindex 累积重复 point
        await self.qdrant.delete_by_dataset(self.COLUMN_COLLECTION, user_id, dataset_id)
        columns = await self.meta_repo.list_columns(dataset_id, datasource_id)
        await self._index_columns(user_id, dataset_id, datasource_id, columns)
        await self.reindex_metrics(user_id, dataset_id, datasource_id)
        return len(columns)

    async def reindex_metrics(
        self, user_id: int, dataset_id: int, datasource_id: int = 0
    ) -> int:
        """重建指标向量：name + 别名 + 描述，各自一条。"""
        await self.qdrant.delete_by_dataset(self.METRIC_COLLECTION, user_id, dataset_id)
        metrics = await self.meta_repo.list_metrics(dataset_id)
        texts: list[str] = []
        payloads: list[dict] = []
        for metric in metrics:
            for text in [metric.name, *metric.alias, metric.description]:
                if not text:
                    continue
                texts.append(text)
                payloads.append(
                    {
                        **self.qdrant.metric_payload(
                            metric,
                            user_id=user_id,
                            dataset_id=dataset_id,
                            datasource_id=datasource_id,
                        ),
                        "embedding_text": text,
                    }
                )
        if texts:
            vectors = await embedding_client_manager.client.aembed_documents(texts)
            await self.qdrant.upsert_vectors(self.METRIC_COLLECTION, vectors, payloads)
        return len(metrics)

    async def _index_columns(
        self,
        user_id: int,
        dataset_id: int,
        datasource_id: int,
        columns: list[ColumnInfoEntity],
    ) -> None:
        embedder = embedding_client_manager.client
        texts: list[str] = []
        payloads: list[dict] = []
        for col in columns:
            for text in [col.description or col.name, *col.alias]:
                if not text:
                    continue
                texts.append(text)
                payloads.append(
                    {
                        **self.qdrant.column_payload(
                            col,
                            user_id=user_id,
                            dataset_id=dataset_id,
                            datasource_id=datasource_id,
                        ),
                        "embedding_text": text,
                    }
                )
        if texts:
            vectors = await embedder.aembed_documents(texts)
            await self.qdrant.upsert_vectors(self.COLUMN_COLLECTION, vectors, payloads)

        docs: list[dict] = []
        for col in columns:
            for value in col.examples:
                docs.append(
                    {
                        "id": f"{dataset_id}:{col.id}:{value}",
                        "user_id": str(user_id),
                        "dataset_id": str(dataset_id),
                        "datasource_id": str(datasource_id),
                        "column_id": col.id,
                        "value": str(value),
                    }
                )
        if docs:
            await self.es.bulk_index(docs)
