"""数据源用例：探测、创建、测试、同步、删除。

约束：本层只拼业务、只调用仓储；不出现 AsyncSession、不构造 ORM。
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import InvalidToken

from app.core.crypto import decrypt_json
from app.core.errors import AppError, NotFoundError
from app.core.log import logger
from app.datasources.mysql_source import MySQLDataSource
from app.entities.meta import ColumnInfoEntity
from app.repositories.es.value_es_repo import ValueESRepository
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.datasource_repo import DataSourceRepository
from app.repositories.mysql.meta_repo import MetaRepository
from app.repositories.mysql.physical_table_repo import PhysicalTableRepository
from app.repositories.qdrant.meta_qdrant_repo import MetaQdrantRepository
from app.services.meta_alias import generate_column_meta
from app.services.meta_builder import collect_samples, infer_roles
from app.services.meta_index_service import MetaIndexService
from app.services.meta_relation import resolve_relations

COLUMN_COLLECTION = MetaIndexService.COLUMN_COLLECTION
class DatasourceService:
    def __init__(
        self,
        datasource_repo: DataSourceRepository,
        dataset_repo: DatasetRepository,
        meta_repo: MetaRepository,
        physical_repo: PhysicalTableRepository,
        index_service: MetaIndexService,
        qdrant: MetaQdrantRepository,
        es: ValueESRepository,
    ) -> None:
        self.repo = datasource_repo
        self.dataset_repo = dataset_repo
        self.meta_repo = meta_repo
        self.physical_repo = physical_repo
        self.index_service = index_service
        self.qdrant = qdrant
        self.es = es
    # ---- 探测：只测试连接并返回表清单，不落库 ----
    @staticmethod
    async def probe(config: dict) -> dict[str, object]:
        source = MySQLDataSource(0, config)
        try:
            await source.test_connection()
            # TableSchema(
            #     name="orders",
            #     comment="订单表",
            #     columns=[
            #         ColumnSchema(name="order_id", type="varchar(32)", comment="订单号"),
            #         ColumnSchema(name="amount", type="decimal(10,2)", comment="金额"),
            #         ColumnSchema(name="order_date", type="datetime", comment="下单时间"),
            #     ],
            # )
            schemas = await source.discover_schema()
        except Exception as exc:
            raise ValueError(f"连接失败：{exc}") from exc
        finally:
            if source.engine is not None:
                await source.engine.dispose()
        return {
            "ok": True,
            "database": config.get("database"),
            "tables": [{"name": s.name, "columns": len(s.columns)} for s in schemas],
        }

    # ---- 创建：数据源 + 数据集 + 选中表 + 索引 ----
    async def create_mysql(
        self,
        *,
        user_id: int,
        name: str,
        config: dict,
        dataset_name: str,
        dataset_description: str = "",
        tables: list[str] | None = None,
    ) -> dict[str, object]:
        source = MySQLDataSource(0, config)
        try:
            await source.test_connection()
            schemas = await source.discover_schema()
        except Exception as exc:
            raise ValueError(f"连接失败：{exc}") from exc

        selected = [s for s in schemas if not tables or s.name in tables]
        if not selected:
            raise ValueError("没有可用的表")

        datasource = await self.repo.create(user_id, "mysql", name, config)
        dataset = await self.dataset_repo.create_with_datasource(
            user_id, dataset_name or name, dataset_description, datasource.id
        )
        samples = await self._collect_samples(source, selected)
        columns = await self._persist_schema(
            dataset.id, selected, datasource.id, samples=samples
        )
        # 表关系建源时推断一次（存 table_relation），问数时直接读，不再每次调 LLM
        relations = await resolve_relations(
            selected,
            source.execute,
            samples,
            source=source,
            roles=self._infer_roles(selected),
        )
        await self.meta_repo.replace_relations(dataset.id, relations)
        await self.repo.set_status(datasource.id, "ok")

        # 把这个数据集的元数据从 MySQL 读出来，重新生成 Qdrant 向量和 ES 索引。
        await self.index_service.reindex_dataset(user_id, dataset.id, datasource_id=datasource.id)
        if source.engine is not None:
            await source.engine.dispose()
        return {
            "datasource_id": datasource.id,
            "dataset_id": dataset.id,
            "tables": len(selected),
            "columns": len(columns),
            "status": "ok",
        }

    # ---- 列表（脱敏）---- 当前用户的数据源列表，并把敏感信息去掉
    async def list_datasources(self, user_id: int) -> list[dict[str, object]]:
        rows = await self.repo.list_by_user(user_id)
        out: list[dict] = []
        for row in rows:
            preview: dict = {}
            if row.kind == "mysql" and row.config_enc:
                try:
                    raw = json.loads(decrypt_json(row.config_enc))
                    preview = {
                        "host": raw.get("host"),
                        "port": raw.get("port"),
                        "database": raw.get("database"),
                    }
                except (InvalidToken, json.JSONDecodeError, KeyError):
                    preview = {}
            out.append(
                {
                    "id": row.id,
                    "kind": row.kind,
                    "name": row.name,
                    "status": row.status,
                    "last_checked": row.last_checked,
                    "config_preview": preview,
                }
            )
        return out
    # ---- 测试已有连接 ----
    async def test(self, user_id: int, datasource_id: int) -> dict[str, object]:
        row = await self.repo.get(user_id, datasource_id)
        if row is None:
            raise NotFoundError("数据源不存在")
        if row.kind != "mysql":
            return {"ok": True, "message": "CSV 数据源无需连接"}
        config = self.repo.read_config(row)
        source = MySQLDataSource(row.id, config)
        try:
            await source.test_connection()
            await self.repo.set_status(row.id, "ok")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001 - 驱动可能抛多种连接异常
            await self.repo.set_status(row.id, "error", str(exc))
            return {"ok": False, "error": str(exc)}
        finally:
            if source.engine is not None:
                await source.engine.dispose()


    # ---- 同步 schema：第一步，只读预览差异 ----
    async def preview_sync(self, user_id: int, datasource_id: int) -> dict[str, object]:
        """读一遍用户库，和本地元数据比对，返回差异（不落库、不建索引）。"""

        row = await self.repo.get(user_id, datasource_id)
        if row is None:
            raise NotFoundError("数据源不存在")
        if row.kind != "mysql":
            return {"new_tables": [], "changed_tables": [], "removed_tables": [],
                    "existing_tables": [], "message": "CSV 数据源结构固定，无需同步"}

        datasets = await self.dataset_repo.list_by_datasource(user_id, datasource_id)
        if not datasets:
            raise NotFoundError("数据集不存在")
        dataset = datasets[0]

        source = MySQLDataSource(row.id, self.repo.read_config(row))
        try:
            schemas = await source.discover_schema()
        except Exception as exc:
            await self.repo.set_status(row.id, "error", str(exc))
            raise ValueError(f"读取结构失败：{exc}") from exc
        finally:
            if source.engine is not None:
                await source.engine.dispose()

        tables = await self.dataset_repo.list_tables(dataset.id)
        existing = {t.physical_name for t in tables}

        new_tables = [
            {"name": s.name, "columns": len(s.columns), "comment": s.comment}
            for s in schemas
            if s.name not in existing
        ]

        # 已有表："新增列 / 类型变化 / 删除列"
        changed_tables: list[dict[str, object]] = []
        for schema in schemas:
            if schema.name not in existing:
                continue
            local = await self.meta_repo.list_columns_by_table(dataset.id, schema.name)
            local_map = {c.name: c for c in local}
            new_columns = [
                {"name": c.name, "type": c.type}
                for c in schema.columns
                if c.name not in local_map
            ]
            type_changed = [
                {"name": c.name, "from": local_map[c.name].type, "to": c.type}
                for c in schema.columns
                if c.name in local_map and local_map[c.name].type != c.type
            ]
            remote_names = {c.name for c in schema.columns}
            dropped_columns = sorted({n for n in local_map if n not in remote_names})
            if new_columns or type_changed or dropped_columns:
                changed_tables.append(
                    {
                        "name": schema.name,
                        "new_columns": new_columns,
                        "type_changed": type_changed,
                        "dropped_columns": dropped_columns,
                    }
                )

        remote_names_all = {s.name for s in schemas}
        removed_tables = sorted(existing - remote_names_all)

        return {
            "dataset_id": dataset.id,
            "new_tables": new_tables,
            "changed_tables": changed_tables,
            "removed_tables": removed_tables,
            "existing_tables": sorted(existing & remote_names_all),
        }

    # ---- 同步 schema ---- 重新去用户的库读一遍表结构，把新增的表补进来，然后版本号 +1、重建索引。
    async def sync(
        self,
        user_id: int,
        datasource_id: int,
        tables: list[str] | None = None,
        drop_columns: bool = False,
        drop_tables: bool = False,
    ) -> dict[str, object]:
        """tables=None 表示处理全部差异。

        drop_columns=True 才删「源表已不存在的列」的元数据；
        drop_tables=True 才删「源库已不存在的表」的元数据。
        """
        row = await self.repo.get(user_id, datasource_id)
        if row is None:
            raise NotFoundError("数据源不存在")
        if row.kind != "mysql":
            return {"dataset_id": None, "added_tables": 0, "message": "CSV 数据源结构固定，无需同步"}
        datasets = await self.dataset_repo.list_by_datasource(user_id, datasource_id)
        if not datasets:
            raise NotFoundError("数据集不存在")
        dataset = datasets[0]
        source = MySQLDataSource(row.id, self.repo.read_config(row))
        try:
            schemas = await source.discover_schema()
        except Exception as exc:
            await self.repo.set_status(row.id, "error", str(exc))
            raise ValueError(f"同步失败：{exc}") from exc
        finally:
            if source.engine is not None:
                await source.engine.dispose()
        samples = await self._collect_samples(source, schemas)

        tables_local = await self.dataset_repo.list_tables(dataset.id)
        existing = {t.physical_name for t in tables_local}
        # 把用户传的表名列表转成 set，方便快速判断“这张表被选中了吗”；None 表示没指定（= 全选）。
        picked = set(tables) if tables is not None else None

        # ① 新表：整表登记
        new_schemas = [
            s for s in schemas if s.name not in existing and (picked is None or s.name in picked)
        ]
        if new_schemas:
            await self._persist_schema(
                dataset.id, new_schemas, datasource_id, samples=samples
            )

        # ② 已有表：加新列、更新类型，删列
        added_columns = 0
        updated_columns = 0
        dropped_columns = 0
        for schema in schemas:
            if schema.name not in existing or (picked is not None and schema.name not in picked):
                continue
            local = await self.meta_repo.list_columns_by_table(dataset.id, schema.name)
            local_map = {c.name: c for c in local}
            to_add: list[ColumnInfoEntity] = []
            to_update: list[ColumnInfoEntity] = []
            for col in schema.columns:
                entity = ColumnInfoEntity(
                    id=f"{dataset.id}:{schema.name}.{col.name}",
                    table_id=schema.name,
                    name=col.name,
                    type=col.type,
                    role=local_map[col.name].role if col.name in local_map else "dimension",
                    description=col.comment or col.name,
                    examples=samples.get(f"{schema.name}.{col.name}", []),
                    alias=[],
                    dataset_id=dataset.id,
                    datasource_id=datasource_id,
                )
                if col.name not in local_map:
                    to_add.append(entity)
                elif local_map[col.name].type != col.type:
                    to_update.append(entity)
            if to_add:
                added_columns += await self.meta_repo.add_columns(dataset.id, to_add)
            if to_update:
                updated_columns += await self.meta_repo.update_columns_meta(dataset.id, to_update)
            if drop_columns:
                remote_names = {c.name for c in schema.columns}
                gone = [name for name in local_map if name not in remote_names]
                if gone:
                    dropped_columns += await self.meta_repo.delete_columns(
                        dataset.id, schema.name, gone
                    )

        # ③ 源库已删的表：默认保留元数据，只有显式要求才删
        dropped_tables = 0
        if drop_tables:
            remote_names_all = {s.name for s in schemas}
            gone_tables = [
                t.physical_name
                for t in tables_local
                if t.physical_name not in remote_names_all
                and (picked is None or t.physical_name in picked)
            ]
            for physical in gone_tables:
                await self.meta_repo.delete_table_meta(dataset.id, physical)
                await self.dataset_repo.delete_table(dataset.id, physical)
                dropped_tables += 1

        changed = bool(
            new_schemas or added_columns or updated_columns or dropped_columns or dropped_tables
        )
        if changed:
            await self.dataset_repo.bump_schema_version(dataset.id)
            # 结构变了，关系也按三层策略重算
            relations = await resolve_relations(
                schemas,
                source.execute,
                samples,
                source=source,
                roles=self._infer_roles(schemas),
            )
            await self.meta_repo.replace_relations(dataset.id, relations)
            # 把一个数据集的所有字段重新向量化 + 重建取值索引
            await self.index_service.reindex_dataset(user_id, dataset.id, datasource_id)

        await self.repo.set_status(row.id, "ok")
        latest = await self.dataset_repo.get(user_id, dataset.id)
        return {
            "dataset_id": dataset.id,
            "added_tables": len(new_schemas),
            "added_columns": added_columns,
            "updated_columns": updated_columns,
            "dropped_columns": dropped_columns,
            "dropped_tables": dropped_tables,
            "schema_version": latest.schema_version if latest else 0,
        }
    # ---- 修改配置：先验证连接，再落库 ----
    async def update(
        self,
        user_id: int,
        datasource_id: int,
        *,
        name: str | None = None,
        config: dict | None = None,
    ) -> dict[str, object]:
        row = await self.repo.get(user_id, datasource_id)
        if row is None:
            raise NotFoundError("数据源不存在")
        if name is None and config is None:
            raise AppError("没有需要修改的内容")

        if config is not None:
            if row.kind != "mysql":
                raise AppError("只有 MySQL 数据源支持修改连接配置")
            probe = MySQLDataSource(0, config)
            try:
                await probe.test_connection()
            except Exception as exc:
                raise AppError(f"连接失败：{exc}") from exc
            finally:
                if probe.engine is not None:
                    await probe.engine.dispose()

        updated = await self.repo.update(user_id, datasource_id, name=name, config=config)
        return {
            "datasource_id": datasource_id,
            "name": updated.name if updated else name,
            "kind": row.kind,
            "config_changed": config is not None,
        }

    # ---- 删除（级联）----
    async def delete(self, user_id: int, datasource_id: int) -> dict[str, object]:
        row = await self.repo.get(user_id, datasource_id)
        if row is None:
            raise NotFoundError("数据源不存在")
        datasets = await self.dataset_repo.list_by_datasource(user_id, datasource_id)
        stats = {"datasources": 1, "datasets": 0, "tables": 0}
        for dataset in datasets:
            tables = await self.dataset_repo.list_tables(dataset.id)
            stats["tables"] += len(tables)
            if row.kind == "csv":
                for table in tables:
                    await self.physical_repo.drop_table(table.physical_name)
            await self.meta_repo.delete_by_dataset(dataset.id)
            await self.dataset_repo.delete(user_id, dataset.id)
            await self.qdrant.delete_by_dataset(COLUMN_COLLECTION, user_id, dataset.id)
            await self.es.delete_by_dataset(user_id, dataset.id)
            stats["datasets"] += 1
        await self.repo.delete(user_id, datasource_id)
        return {"deleted": stats}

    # ---- 内部：把发现的 schema 写成元数据 ----
    # 采样与 role 推断已抽到 meta_builder，这里只做薄封装（保留原调用点）

    async def _collect_samples(self, source, schemas) -> dict[str, list]:
        """采样示例值（日期类放宽到 200，其它 50）。设 META_DISABLE_SAMPLING=1 可关闭。"""
        if os.getenv("META_DISABLE_SAMPLING") == "1":
            logger.warning("META_DISABLE_SAMPLING=1，跳过示例值采样")
            return {}
        return await collect_samples(source, schemas)

    @staticmethod
    def _infer_roles(schemas) -> dict[str, str]:
        """主键取真实 schema 信息，外键看是否同名于其他表主键，其余按度量/维度判定。"""
        return infer_roles(schemas)

    async def _persist_schema(
        self,
        dataset_id: int,
        schemas,
        datasource_id: int = 0,
        samples: dict[str, list] | None = None,
    ) -> list[ColumnInfoEntity]:
        samples = samples or {}
        roles = self._infer_roles(schemas)
        columns: list[ColumnInfoEntity] = []
        for schema in schemas:
            # 存dataset_tables
            await self.dataset_repo.add_table(dataset_id, schema.name, schema.name, 0)

            # 生成业务描述 + 中文别名（每表 1 次 LLM 调用）
            # description 决定 Qdrant 第一条向量的语义，alias 每个生成一条向量
            metas = await generate_column_meta(schema, samples)

            table_columns: list[ColumnInfoEntity] = [
                ColumnInfoEntity(
                    # id 带上 dataset_id：不同数据集可能有同名表/字段
                    id=f"{dataset_id}:{schema.name}.{col.name}",
                    table_id=schema.name,
                    name=col.name,
                    type=col.type,
                    role=roles.get(f"{schema.name}.{col.name}", "dimension"),
                    description=(
                        col.comment
                        or metas.get(col.name, {}).get("description")
                        or col.name
                    ),
                    examples=samples.get(f"{schema.name}.{col.name}", []),
                    alias=metas.get(col.name, {}).get("alias", []),
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                )
                for col in schema.columns
            ]
            columns.extend(table_columns)
            # 存table_info
            await self.meta_repo.save_table_with_columns(
                dataset_id,
                f"{dataset_id}:{schema.name}",
                schema.name,
                "fact",
                schema.comment or schema.name,
                table_columns,
            )

            # 指标需要人工配置
        return columns
