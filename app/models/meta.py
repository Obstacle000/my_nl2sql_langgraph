"""元数据：表 / 字段 / 指标（全部带 dataset_id 做隔离）。"""

import time

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TableInfo(Base):
    __tablename__ = "table_info"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # ds1_t0
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))                   # 业务表名
    role: Mapped[str] = mapped_column(String(16), default="fact")    # fact / dim
    description: Mapped[str] = mapped_column(Text, default="")


class ColumnInfo(Base):
    __tablename__ = "column_info"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)   # 表.字段
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id"), index=True)
    table_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(64), default="varchar(255)")
    role: Mapped[str] = mapped_column(String(32), default="dimension")
    description: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[str] = mapped_column(Text, default="[]")        # JSON 字符串
    alias: Mapped[str] = mapped_column(Text, default="[]")           # JSON 字符串


class TableRelation(Base):
    """表间关联关系（建源时推断一次，问数时直接读）。"""

    __tablename__ = "table_relation"

    id: Mapped[str] = mapped_column(String(320), primary_key=True)   # from=to
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id"), index=True)
    from_table: Mapped[str] = mapped_column(String(128))
    from_column: Mapped[str] = mapped_column(String(128))
    to_table: Mapped[str] = mapped_column(String(128))
    to_column: Mapped[str] = mapped_column(String(128))


class MetricInfo(Base):
    __tablename__ = "metric_info"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)   # dataset:指标名
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    relevant_columns: Mapped[str] = mapped_column(Text, default="[]")  # JSON 字符串
    alias: Mapped[str] = mapped_column(Text, default="[]")
    expression: Mapped[str] = mapped_column(Text, default="")          # 口径表达式
    created_at: Mapped[float] = mapped_column(BigInteger, default=lambda: int(time.time()))
