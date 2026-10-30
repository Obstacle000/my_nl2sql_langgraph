"""数据集与物理表登记：一个 dataset = 用户上传的一批 CSV。"""

import time

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    # 指向 datasources.id：CSV 上传会建一个 kind=csv 的数据源
    datasource_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(BigInteger, default=lambda: int(time.time()))


class DatasetTable(Base):
    __tablename__ = "dataset_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, ForeignKey("datasets.id"), index=True)
    table_name: Mapped[str] = mapped_column(String(128))       # 业务名（展示给模型）
    physical_name: Mapped[str] = mapped_column(String(128))   # 物理名 ds1_t0(真实表名)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(BigInteger, default=lambda: int(time.time()))
