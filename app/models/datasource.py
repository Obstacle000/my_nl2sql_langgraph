"""数据源：用户接入的一个来源（一份 CSV 或一个 MySQL 库）。"""

import time

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataSource(Base):
    __tablename__ = "datasources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))              # csv / mysql
    name: Mapped[str] = mapped_column(String(128))
    config_enc: Mapped[str] = mapped_column(Text, default="")  # 加密后的连接配置（csv 为空）
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown/ok/error
    error: Mapped[str] = mapped_column(Text, default="")
    last_checked: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[float] = mapped_column(BigInteger, default=lambda: int(time.time()))
