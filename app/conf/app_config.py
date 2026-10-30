"""应用配置：OmegaConf 加载 yaml + 环境变量插值。"""

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from omegaconf import OmegaConf

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class MySQLConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "nl2sql"


@dataclass
class RedisConfig:
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: str = ""


@dataclass
class QdrantConfig:
    host: str = "127.0.0.1"
    port: int = 6333
    embedding_size: int = 1024


@dataclass
class ESConfig:
    host: str = "127.0.0.1"
    port: int = 9200
    index_name: str = "nl2sql_values"


@dataclass
class EmbeddingConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    dim: int = 1024


@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@dataclass
class AuthConfig:
    jwt_secret: str = "dev-secret"
    access_token_minutes: int = 120


@dataclass
class CacheConfig:
    sql_ttl_seconds: int = 604800
    semantic_threshold: float = 0.95
    semantic_ttl_seconds: int = 604800


@dataclass
class AppConfig:
    logging: LoggingConfig
    mysql: MySQLConfig
    redis: RedisConfig
    qdrant: QdrantConfig
    elasticsearch: ESConfig
    embedding: EmbeddingConfig
    llm: LLMConfig
    auth: AuthConfig
    cache: CacheConfig

# 四步：注入环境变量 → 读 yaml → 生成带类型和默认值的骨架 → 合并并转成对象。
load_dotenv(PROJECT_ROOT / ".env")

_context = OmegaConf.load(PROJECT_ROOT / "conf" / "app_config.yaml")
_schema = OmegaConf.structured(AppConfig)
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(_schema, _context))
