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
    name: str


class ConversationCreateRequest(BaseModel):
    """新建会话：绑定一个数据集。"""

    dataset_id: int
    title: str = ""


class QueryRequest(BaseModel):
    dataset_id: int
    question: str = Field(min_length=1, max_length=500)
    conversation_id: int | None = None      # 传了就走多轮（带最近 3 轮历史）


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


class MetricSaveRequest(BaseModel):
    """指标口径：expression 里用 {表.字段} 占位。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    expression: str = ""
    relevant_columns: list[str] = Field(default_factory=list)
    alias: list[str] = Field(default_factory=list)


class DataSourceUpdateRequest(BaseModel):
    """只改名字或连接配置；都为空则什么都不做。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: DataSourceConfig | None = None


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
