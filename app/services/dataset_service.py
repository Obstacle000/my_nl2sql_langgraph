"""数据集用例：建数据集、上传 CSV 建表并建索引。

约束：本层只拼业务、只调用仓储；不出现 AsyncSession、不构造 ORM。
"""

import io
from pathlib import Path

import pandas as pd

from app.core.log import logger
from app.datasources.base import ColumnSchema, TableSchema
from app.datasources.registry import DataSourceRegistry
from app.entities.meta import ColumnInfoEntity
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.services.meta_builder import collect_samples_table, enrich_columns, infer_roles
from app.services.meta_index_service import MetaIndexService

MAX_ROWS = 100_000


class DatasetService:
    def __init__(
        self,
        dataset_repo: DatasetRepository,
        meta_repo: MetaRepository,
        physical_repo: PhysicalTableRepository,
        index_service: MetaIndexService,
        registry: DataSourceRegistry,
        upload_dir: Path,
    ) -> None:
        self.dataset_repo = dataset_repo
        self.meta_repo = meta_repo
        self.physical_repo = physical_repo
        self.index_service = index_service
        self.registry = registry
        self.upload_dir = upload_dir

    async def create_dataset(self, *, user_id: int, name: str, description: str = "") -> dict:
        """新建 CSV 数据集：同时建一个 kind=csv 的数据源（MVP 1:1）。"""
        dataset = await self.dataset_repo.create_csv_dataset(user_id, name, description)
        return {"dataset_id": dataset.id, "name": dataset.name}

    async def add_csv_table(
        self,
        *,
        user_id: int,
        dataset_id: int,
        table_name: str,
        csv_bytes: bytes,
        filename: str,
    ) -> dict:
        """往已有数据集追加一张表：建物理表 → 灌数据 → 元数据 → 索引。"""
        frame = self._read_csv(csv_bytes)
        if frame.empty:
            raise ValueError("CSV 没有数据行")
        if len(frame) > MAX_ROWS:
            raise ValueError(f"行数 {len(frame)} 超过上限 {MAX_ROWS}，请拆分或使用离线导入")

        # 并发保护：先拿 Redis 锁，再做任何读操作。
        # 若先读库再拿锁，事务快照已建立，看不到后来提交的表 →
        # list_tables 会算错序号，导致物理表/列元数据重名。
        from app.clients.redis_client_manager import redis_client_manager
        from app.core.redis_lock import RedisLock

        async with RedisLock(
            redis_client_manager.client, f"upload:dataset:{dataset_id}"
        ):
            return await self._add_csv_table_locked(
                user_id=user_id,
                dataset_id=dataset_id,
                table_name=table_name,
                frame=frame,
                csv_bytes=csv_bytes,
                filename=filename,
            )

    async def _add_csv_table_locked(
        self,
        *,
        user_id: int,
        dataset_id: int,
        table_name: str,
        frame,
        csv_bytes: bytes,
        filename: str,
    ) -> dict:
        """真正的建表流程：调用方必须已持有该数据集的锁。"""
        dataset = await self.dataset_repo.get(user_id, dataset_id)
        if dataset is None:
            raise ValueError("数据集不存在")

        existing = await self.dataset_repo.list_tables(dataset_id)
        physical = self._next_physical_name(dataset_id, existing)

        # ① 建物理表并灌数据
        # 先清一次：上次上传若中途失败，CREATE TABLE 已隐式提交，会留下孤儿表
        await self.physical_repo.drop_if_exists(physical)
        created = False
        try:
            await self.physical_repo.create_table(
                physical, [(self._safe_col(c), self._sql_type(frame[c])) for c in frame.columns]
            )
            created = True
            await self.physical_repo.insert_rows(
                physical,
                [self._safe_col(c) for c in frame.columns],
                [
                    tuple(None if pd.isna(v) else v for v in row)
                    for row in frame.itertuples(index=False, name=None)
                ],
            )

            # ② 采样：INSERT 还在本事务里（未提交），必须用同一 session 查物理表
            samples = await collect_samples_table(
                self.physical_repo,
                physical,
                [(self._safe_col(c), self._sql_type(frame[c])) for c in frame.columns],
            )
            await self.dataset_repo.add_table(dataset_id, table_name, physical, len(frame))

            # ③ 元数据 + LLM 富化
            columns = self._build_columns(
                physical,
                frame,
                dataset_id=dataset_id,
                datasource_id=dataset.datasource_id or 0,
                samples=samples,
            )
            metas = await enrich_columns(physical, columns, samples)
            for column in columns:
                meta = metas.get(column.name) or {}
                if meta.get("description"):
                    column.description = meta["description"]
                if meta.get("alias"):
                    column.alias = meta["alias"]
            await self.meta_repo.save_table_with_columns(
                dataset_id,
                f"{dataset_id}:{physical}",
                table_name,
                "fact",
                f"用户上传的 CSV：{table_name}",
                columns,
            )

            # ④ 索引：只索引这张新表，不重建整个数据集
            await self.index_service.index_table(
                user_id,
                dataset_id,
                f"{dataset_id}:{physical}",
                datasource_id=dataset.datasource_id or 0,
            )
        except Exception:
            # DDL 已提交，回滚救不了表结构 → 显式删除，避免留下孤儿表
            # 若此时 session 已进入失败状态，这次删除可能也失败，
            # 下次上传前的 drop_if_exists 会兜底
            if created:
                try:
                    await self.physical_repo.drop_if_exists(physical)
                except Exception as cleanup_error:  # noqa: BLE001
                    logger.warning(f"清理孤儿表 {physical} 失败：{cleanup_error}")
            raise

        # ⑤ 留档
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (self.upload_dir / f"{physical}_{filename}").write_bytes(csv_bytes)

        return {
            "dataset_id": dataset_id,
            "table_name": table_name,
            "physical_name": physical,
            "rows": len(frame),
            "columns": len(columns),
        }

    # -- 纯函数（无 IO） --

    @staticmethod
    def _read_csv(raw: bytes) -> pd.DataFrame:
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("文件编码无法识别（支持 UTF-8 / GBK）")

    @staticmethod
    def _next_physical_name(dataset_id: int, existing: list) -> str:
        """取"已有最大序号 + 1"，避免删表/失败后重号。"""
        numbers = []
        for table in existing:
            physical_name = getattr(table, "physical_name", "") or ""
            suffix = physical_name.rsplit("_t", 1)[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
        return f"ds{dataset_id}_t{max(numbers, default=-1) + 1}"

    @classmethod
    def _safe_col(cls, name: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name))
        return cleaned or "col"

    @classmethod
    def _sql_type(cls, series: pd.Series) -> str:
        if pd.api.types.is_integer_dtype(series):
            return "bigint"
        if pd.api.types.is_float_dtype(series):
            return "decimal(18,4)"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "datetime"
        return "varchar(255)"

    @classmethod
    def _build_columns(
        cls,
        physical: str,
        frame: pd.DataFrame,
        dataset_id: int = 0,
        datasource_id: int = 0,
        samples: dict[str, list] | None = None,
    ) -> list[ColumnInfoEntity]:
        samples = samples or {}
        # 先按类型造 schema，交给统一的 role 推断（CSV 无主键，primary 全 False）
        schemas = [
            TableSchema(
                name=physical,
                columns=[
                    ColumnSchema(name=cls._safe_col(col), type=cls._sql_type(frame[col]))
                    for col in frame.columns
                ],
            )
        ]
        roles = infer_roles(schemas)

        # 与 MySQL 路径保持一致：id / table_id 都带 dataset 前缀
        table_id = f"{dataset_id}:{physical}"

        columns: list[ColumnInfoEntity] = []
        for col in frame.columns:
            series = frame[col]
            safe_name = cls._safe_col(col)
            columns.append(
                ColumnInfoEntity(
                    id=f"{table_id}.{safe_name}",
                    table_id=table_id,
                    name=safe_name,
                    type=cls._sql_type(series),
                    role=roles.get(f"{physical}.{safe_name}", "dimension"),
                    description=str(col),
                    examples=samples.get(f"{physical}.{safe_name}", []),
                    alias=[],
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                )
            )
        return columns
