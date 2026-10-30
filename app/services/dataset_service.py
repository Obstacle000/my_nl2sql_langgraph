"""数据集用例：建数据集、上传 CSV 建表并建索引。

约束：本层只拼业务、只调用仓储；不出现 AsyncSession、不构造 ORM。
"""

import io
from pathlib import Path

import pandas as pd

from app.entities.meta import ColumnInfoEntity
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.services.meta_index_service import MetaIndexService

MAX_ROWS = 100_000


class DatasetService:
    def __init__(
        self,
        dataset_repo: DatasetRepository,
        meta_repo: MetaRepository,
        physical_repo: PhysicalTableRepository,
        index_service: MetaIndexService,
        upload_dir: Path,
    ) -> None:
        self.dataset_repo = dataset_repo
        self.meta_repo = meta_repo
        self.physical_repo = physical_repo
        self.index_service = index_service
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

        dataset = await self.dataset_repo.get(user_id, dataset_id)
        if dataset is None:
            raise ValueError("数据集不存在")

        existing = await self.dataset_repo.list_tables(dataset_id)
        physical = f"ds{dataset_id}_t{len(existing)}"

        # ① 建物理表并灌数据
        await self.physical_repo.create_table(
            physical, [(self._safe_col(c), self._sql_type(frame[c])) for c in frame.columns]
        )
        await self.physical_repo.insert_rows(
            physical,
            [self._safe_col(c) for c in frame.columns],
            [
                tuple(None if pd.isna(v) else v for v in row)
                for row in frame.itertuples(index=False, name=None)
            ],
        )

        # ② 元数据（仓储内同一事务）
        columns = self._build_columns(
            physical, frame, dataset_id=dataset_id, datasource_id=dataset.datasource_id or 0
        )
        await self.dataset_repo.add_table(dataset_id, table_name, physical, len(frame))
        await self.meta_repo.save_table_with_columns(
            dataset_id,
            physical,
            table_name,
            "fact",
            f"用户上传的 CSV：{table_name}",
            columns,
        )

        # ③ 索引：从 MySQL 读出元数据再建
        await self.index_service.reindex_dataset(
            user_id, dataset_id, datasource_id=dataset.datasource_id or 0
        )

        # ④ 留档
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
    def _safe_col(name: str) -> str:
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
    ) -> list[ColumnInfoEntity]:
        columns: list[ColumnInfoEntity] = []
        for col in frame.columns:
            series = frame[col]
            examples = [str(v) for v in series.dropna().unique()[:5]]
            columns.append(
                ColumnInfoEntity(
                    id=f"{physical}.{cls._safe_col(col)}",
                    table_id=physical,
                    name=cls._safe_col(col),
                    type=cls._sql_type(series),
                    role="dimension",
                    description=str(col),
                    examples=examples,
                    alias=[],
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                )
            )
        return columns
