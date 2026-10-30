"""请求 / 响应模型。"""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DatasetCreateResponse(BaseModel):
    dataset_id: int
    tables: list[str]
    rows: int


class QueryRequest(BaseModel):
    dataset_id: int
    question: str = Field(min_length=1, max_length=500)


class DataSourceConfig(BaseModel):
    """MySQL 连接配置（只在请求里出现，落库前加密）。"""

    host: str
    port: int = 3306
    user: str
    password: str
    database: str


class DataSourceProbeRequest(BaseModel):
    kind: str = "mysql"
    config: DataSourceConfig


class DatasetSpec(BaseModel):
    # 数据集名是给这个“查询范围”起的人话名字，不是表名的拼接。
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    tables: list[str] | None = None
    drop_columns: bool = False
    drop_tables: bool = False
    # name = ("销售分析",)  # 必填，1~128 字符
    # description = ("订单与退货",)  # 可空
    # tables = (["orders", "refunds"],)  # None = 全部表


class DataSourceCreateRequest(BaseModel):
    kind: str = "mysql"
    name: str = Field(min_length=1, max_length=128)
    config: DataSourceConfig # 连接信息
    dataset: DatasetSpec # 要建的数据集


class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""


class TableCreateResponse(BaseModel):
    dataset_id: int
    table_name: str
    physical_name: str
    rows: int
    columns: int


class SyncRequest(BaseModel):
    """同步 schema 时用户勾选要新增的表；不传表示全部新增。"""

    tables: list[str] | None = None
