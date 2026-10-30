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
    def exact_key(user_id: int, dataset_id: int, schema_version: int, question: str) -> str:
        digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()[:32]
        return f"sql:{user_id}:{dataset_id}:{schema_version}:{digest}"

    @staticmethod
    def semantic_key(user_id: int, dataset_id: int, schema_version: int) -> str:
        return f"sqlvec:{user_id}:{dataset_id}:{schema_version}"

    async def get_exact(
        self, user_id: int, dataset_id: int, schema_version: int, question: str
    ) -> str | None:
        key = self.exact_key(user_id, dataset_id, schema_version, question)
        payload = await self.client.get(key)
        if payload is None:
            return None
        return json.loads(payload).get("sql")

    async def set_exact(
        self, user_id: int, dataset_id: int, schema_version: int, question: str, sql: str
    ) -> None:
        key = self.exact_key(user_id, dataset_id, schema_version, question)
        await self.client.set(
            key, json.dumps({"sql": sql}, ensure_ascii=False), ex=self.config.sql_ttl_seconds
        )

    async def get_semantic(
        self,
        user_id: int,
        dataset_id: int,
        schema_version: int,
        vector: list[float],
    ) -> tuple[str, float] | None:
        """在同类问题的向量集合里找最相似的一条，超过阈值才复用。"""
        key = self.semantic_key(user_id, dataset_id, schema_version)
        entries = await self.client.hgetall(key)
        best_sql: str | None = None
        best_score = 0.0
        for payload in entries.values():
            item: dict[str, Any] = json.loads(payload)
            score = cosine(vector, item["vector"])
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
    ) -> None:
        key = self.semantic_key(user_id, dataset_id, schema_version)
        digest = hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()[:16]
        await self.client.hset(
            key,
            digest,
            json.dumps({"vector": vector, "sql": sql}, ensure_ascii=False),
        )
        await self.client.expire(key, self.config.semantic_ttl_seconds)

    async def clear_dataset(self, user_id: int, dataset_id: int, schema_version: int) -> None:
        """schema 变更后清掉旧缓存（版本号已变，这里顺手清）。"""
        await self.client.delete(self.semantic_key(user_id, dataset_id, schema_version))
