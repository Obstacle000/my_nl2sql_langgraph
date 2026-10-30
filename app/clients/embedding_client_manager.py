"""Embedding：OpenAI 兼容的云向量服务（如千问 text-embedding-v3）。"""


from langchain_openai import OpenAIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self.client: OpenAIEmbeddings | None = None

    def init(self) -> None:
        self.client = OpenAIEmbeddings(
            model=self.config.model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            dimensions=self.config.dim,
            chunk_size=10,
            # 兼容非 OpenAI 服务：不要把文本转成 token 数组
            check_embedding_ctx_length=False,
        )


embedding_client_manager = EmbeddingClientManager(app_config.embedding)
