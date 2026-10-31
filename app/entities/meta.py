"""业务实体：与 ORM 解耦，供 Agent 使用。

多租户约定：
  · dataset_id / datasource_id 用于检索层过滤（Qdrant payload、ES 文档）
  · 默认值 0 表示“未设置”，避免改造过程中构造处全部报错
  · 数据库表里不冗余存这两个字段，以 datasets 为单一事实源
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnInfoEntity:
    id: str                  # "表.字段"
    table_id: str            # 物理表名（或 MySQL 里的真实表名）
    name: str                # 列名
    type: str                # bigint / decimal(18,4) / varchar(255) / datetime
    role: str                # primary_key / foreign_key / dimension / measure
    description: str = ""
    examples: list[Any] = field(default_factory=list)
    alias: list[str] = field(default_factory=list)
    # 多租户：写索引时带进 payload，检索时用来过滤
    dataset_id: int = 0
    datasource_id: int = 0


@dataclass
class MetricInfoEntity:
    id: str                  # "{dataset_id}:{指标名}"
    name: str
    description: str = ""
    expression: str = ""     # 口径，如 SUM({t_ord.amt}) / COUNT(DISTINCT {t_ord.cust_no})
    relevant_columns: list[str] = field(default_factory=list)
    alias: list[str] = field(default_factory=list)
    dataset_id: int = 0
    datasource_id: int = 0


@dataclass
class ValueInfoEntity:
    id: str                  # "{dataset_id}:{column_id}:{value}"
    value: str
    column_id: str
    dataset_id: int = 0
    datasource_id: int = 0
