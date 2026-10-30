"""问数历史：用于审计、评测与缓存命中统计。"""

import time

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer, index=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text, default="")
    hit_cache: Mapped[int] = mapped_column(Integer, default=0)       # 0/1
    rows_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")    # ok / error
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(BigInteger, default=lambda: int(time.time()))
