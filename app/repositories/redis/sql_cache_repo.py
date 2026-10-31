"""Redis：SQL 缓存（精确 + 语义）。

多租户关键：key 必须含 user_id + dataset_id + schema_version。
"""

import hashlib
import json
import math
import re
from typing import Any

from redis.asyncio import Redis

from app.conf.app_config import CacheConfig


def normalize_question(text: str) -> str:
    """去空白与常见中英文标点，避免同一问题的不同写法各存一份。"""
    return re.sub(r"[\s，。？！；：、,.?!;:]+", "", (text or "").lower())


# 关键度量概念：同一句话只差这几个词，语义完全不同，不能复用缓存
METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "sales": ("销售额", "销售金额", "营收", "gmv", "成交额", "成交总额"),
    "amount": ("金额", "金额合计", "总价"),
    "quantity": ("销量", "数量", "件数", "卖了多少"),
    "orders": ("订单数", "单量", "订单量", "多少单"),
    "aov": ("客单价", "平均订单金额", "客单金额"),
    "avg_qty": ("平均件数", "每单件数", "平均购买件数"),
    "customers": ("客户数", "用户数", "多少客户", "多少用户"),
}


def metric_tags(text: str) -> set[str]:
    """抽出这句话涉及哪些度量概念。"""
    lowered = (text or "").lower()
    return {
        tag
        for tag, words in METRIC_PATTERNS.items()
        if any(word in lowered for word in words)
    }


# 这些标签过于泛化（"金额"常常只是修饰词），不参与阻断判断
SOFT_TAGS = {"amount"}


def metrics_compatible(query: str, cached_question: str) -> bool:
    """比对"硬度量词"：两边都有时要求一致；任一侧没有就放行。

    amount（金额）属于泛化词，单独出现不做阻断，
    避免"销售额总金额" vs "总销售额" 这种同义改写被误杀。
    """
    query_tags = metric_tags(query) - SOFT_TAGS
    cached_tags = metric_tags(cached_question) - SOFT_TAGS
    if not query_tags or not cached_tags:
        return True
    return query_tags == cached_tags


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SQLCacheRepository:
    def __init__(self, client: Redis, config: CacheConfig) -> None:
        self.client = client
        self.config = config

    @staticmethod
    def exact_key(
        user_id: int,
        dataset_id: int,
        schema_version: int,
        question: str,
        context: str = "",
    ) -> str:
        digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()[:32]
        # context 为空时 key 与旧格式完全一致，旧缓存继续有效
        suffix = f":{context}" if context else ""
        return f"sql:{user_id}:{dataset_id}:{schema_version}:{digest}{suffix}"

    @staticmethod
    def semantic_key(user_id: int, dataset_id: int, schema_version: int) -> str:
        return f"sqlvec:{user_id}:{dataset_id}:{schema_version}"

    async def get_exact(
        self,
        user_id: int,
        dataset_id: int,
        schema_version: int,
        question: str,
        context: str = "",
    ) -> str | None:
        key = self.exact_key(user_id, dataset_id, schema_version, question, context)
        payload = await self.client.get(key)
        if payload is None:
            return None
        return json.loads(payload).get("sql")

    async def set_exact(
        self,
        user_id: int,
        dataset_id: int,
        schema_version: int,
        question: str,
        sql: str,
        context: str = "",
    ) -> None:
        key = self.exact_key(user_id, dataset_id, schema_version, question, context)
        await self.client.set(
            key, json.dumps({"sql": sql}, ensure_ascii=False), ex=self.config.sql_ttl_seconds
        )
    # 向量以 JSON 存在 Redis 的 hash 里，余弦相似度是 Python 手算的。
    async def get_semantic(
        self,
        user_id: int,
        dataset_id: int,
        schema_version: int,
        vector: list[float],
        context: str = "",
        question: str = "",
    ) -> tuple[str, float] | None:
        """在同类问题的向量集合里找最相似的一条，超过阈值才复用。

        context 不同的一律跳过：同一句话在不同上下文里 SQL 可能不同。
        """
        key = self.semantic_key(user_id, dataset_id, schema_version)
        # 用key取redis里找entries
        # entries:
        # {
        #     "9f3a1b2c4d5e6f70": '{"vector": [0.0123, -0.0456, ...], "sql": "SELECT SUM(amount) AS ..."}',
        #     "aa11bb22cc33dd44": '{"vector": [0.0087, 0.0210, ...], "sql": "SELECT COUNT(*) AS ..."}',
        # }
        #   ↑ field（问题 hash 前 16 位）        ↑ value（JSON 字符串）
        entries = await self.client.hgetall(key)
        best_sql: str | None = None
        best_score = 0.0
        for payload in entries.values():
            item: dict[str, Any] = json.loads(payload)
            if (item.get("ctx") or "") != context:
                continue
            # 护栏：度量词不一致的（销售额 vs 销量）直接跳过，不看相似度
            if not metrics_compatible(question, str(item.get("q") or "")):
                continue
            # # 进行余弦相似度检验
            score = cosine(vector, item["vector"])
            # 找到最相似的
            if score > best_score:
                best_score, best_sql = score, item["sql"]
        if best_sql is not None and best_score >= self.config.semantic_threshold:
            return best_sql, best_score
        return None

    async def set_semantic(
        self,
        user_id: int,
        dataset_id: int,
        schema_version: int,
        question: str,
        vector: list[float],
        sql: str,
        context: str = "",
    ) -> None:
        key = self.semantic_key(user_id, dataset_id, schema_version)
        digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()[:16]
        field = f"{context}:{digest}" if context else digest
        await self.client.hset(
            key,
            field,
            json.dumps(
                {"vector": vector, "sql": sql, "ctx": context, "q": question},
                ensure_ascii=False,
            ),
        )
        await self.client.expire(key, self.config.semantic_ttl_seconds)

    async def clear_dataset(self, user_id: int, dataset_id: int, schema_version: int) -> None:
        """schema 变更后清掉旧缓存（版本号已变，这里顺手清）。"""
        await self.client.delete(self.semantic_key(user_id, dataset_id, schema_version))
