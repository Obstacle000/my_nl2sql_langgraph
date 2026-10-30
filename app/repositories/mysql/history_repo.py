"""问数历史仓储。"""

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.history import QueryHistory


class HistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        user_id: int,
        dataset_id: int,
        question: str,
        sql: str,
        hit_cache: bool,
        rows_count: int,
        latency_ms: int,
        status: str = "ok",
        error: str = "",
    ) -> None:
        """单条审计写入：自己提交，不参与用例事务（问数链路不持事务）。"""
        self.session.add(
            QueryHistory(
                user_id=user_id,
                dataset_id=dataset_id,
                question=question,
                sql=sql,
                hit_cache=1 if hit_cache else 0,
                rows_count=rows_count,
                latency_ms=latency_ms,
                status=status,
                error=error,
                created_at=time.time(),
            )
        )
        await self.session.commit()
