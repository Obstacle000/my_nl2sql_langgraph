"""ES：字段取值全文索引（多租户：文档带 user_id + dataset_id）。"""

from typing import Any

from elasticsearch import AsyncElasticsearch

from app.conf.app_config import app_config


class ValueESRepository:
    index_name = app_config.elasticsearch.index_name

    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def ensure_index(self) -> None:
        if await self.client.indices.exists(index=self.index_name):
            return
        await self.client.indices.create(
            index=self.index_name,
            mappings={
                "dynamic": False,
                "properties": {
                    "id": {"type": "keyword"},
                    "user_id": {"type": "keyword"},
                    "dataset_id": {"type": "keyword"},
                    "datasource_id": {"type": "keyword"},
                    "column_id": {"type": "keyword"},
                    "value": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_max_word",
                        "fields": {"kw": {"type": "keyword"}}, 
                    },
                },
            },
        )

    
    async def bulk_index(self, docs: list[dict[str, Any]], batch_size: int = 200) -> None:
        await self.ensure_index()
        # batch_size = 一批处理多少条，这里指一次 bulk 请求提交多少个文档。
        for i in range(0, len(docs), batch_size):
            operations: list[dict[str, Any]] = []
            # Elasticsearch 的 _bulk 协议：每两行一组，不能只发文档
            for doc in docs[i : i + batch_size]:
                operations.append({"index": {"_index": self.index_name, "_id": doc["id"]}})
                operations.append(doc)
                # operations = [
                #     {"index": {"_index": "value_index", "_id": "2:orders.region:华北"}},   # 动作行
                #     {"id": "2:orders.region:华北", "value": "华北", "column_id": "...", ...},  # 文档行
                #     {"index": {"_index": "value_index", "_id": "2:orders.region:华东"}},
                #     {"id": "...", "value": "华东", ...},
                # ]
            # bulk() 是 Elasticsearch 客户端的批量写入方法（AsyncElasticsearch.bulk）
            await self.client.bulk(operations=operations)

    async def delete_by_dataset(self, user_id: int, dataset_id: int) -> int:
        """删除某数据集的全部取值文档。"""
        resp = await self.client.delete_by_query(
            index=self.index_name,
            query={
                "bool": {
                    "filter": [
                        {"term": {"user_id": str(user_id)}},
                        {"term": {"dataset_id": str(dataset_id)}},
                    ]
                }
            },
        )
        return resp.get("deleted", 0)

    async def search(
        self,
        keyword: str,
        *,
        user_id: int,
        dataset_id: int,
        limit: int = 20,
        min_score: float = 0.6,
    ) -> list[dict[str, Any]]:
        resp = await self.client.search(
            index=self.index_name,
            query={
                "bool": {
                    "must": [{"match": {"value": keyword}}],
                    "filter": [
                        {"term": {"user_id": user_id}},
                        {"term": {"dataset_id": dataset_id}},
                    ],
                }
            },
            size=limit,
            min_score=min_score,
        )
        # 提问:不是精确匹配吗 为什么还有score
        # 答: 首先,ES在存储时对原文分词,查询时对原query分词match
        # 假设往ES里存[value:华北],用户输入华北地区,ES首先会用ik分词成["华北","地区"]
        # 第 1 条含"华北" → 命中，但 score 低一些（只匹配 1/2 个词，~2.0）
        return [hit["_source"] for hit in resp["hits"]["hits"]]
