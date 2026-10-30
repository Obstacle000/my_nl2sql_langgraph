"""合并三路召回：去重 → 补指标依赖字段 → 命中值标注 → 补主外键 → 按表聚合。"""

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.state import Nl2SqlState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


async def infer_relations(
    foreign_keys: list[dict], primary_keys: list[dict]
) -> list[str]:
    """让 LLM 根据 role + examples 判断外键指向哪个主键，返回 "a.b = c.d" 列表。"""
    prompt = PromptTemplate(
        template=load_prompt("infer_relations"),
        input_variables=["foreign_keys", "primary_keys"],
    )
    chain = prompt | llm | JsonOutputParser()
    mapping = await chain.ainvoke(
        {
            "foreign_keys": yaml.dump(foreign_keys, allow_unicode=True, sort_keys=False),
            "primary_keys": yaml.dump(primary_keys, allow_unicode=True, sort_keys=False),
        }
    )
    if not isinstance(mapping, dict):
        return []
    return [f"{fk} = {pk}" for fk, pk in mapping.items() if isinstance(pk, str) and pk]


async def merge_retrieved_info(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "合并召回", "status": "running"})
    ctx = runtime.context
    meta = ctx["meta_repo"]
    dataset_id = ctx["dataset_id"]

    # ① 字段去重（同一字段多条向量 → payload.id 相同）
    columns: dict[str, dict] = {c["id"]: c for c in state.get("retrieved_column_infos", [])}

    # ② 指标依赖的字段，没召回就从 MySQL 补
    for metric in state.get("retrieved_metric_infos", []):
        for column_id in metric.get("relevant_columns", []):
            if column_id in columns:
                continue
            entities = await meta.get_columns_by_ids(dataset_id, [column_id])
            for entity in entities:
                columns[entity.id] = {
                    "id": entity.id,
                    "table_id": entity.table_id,
                    "name": entity.name,
                    "type": entity.type,
                    "role": entity.role,
                    "description": entity.description,
                    "examples": entity.examples,
                    "alias": entity.alias,
                }

    # ③ 命中取值：单独记 matched_values，同时插到 examples 最前面
    #    （插到前面是为了后面截断时命中值一定保留）
    matched: list[dict] = []
    for value in state.get("retrieved_value_infos", []):
        column_id = value["column_id"]
        matched.append({"column_id": column_id, "value": value["value"]})
        if column_id in columns:
            examples = columns[column_id].setdefault("examples", [])
            if value["value"] not in examples:
                examples.insert(0, value["value"])

    # ④ 按表分组
    grouped: dict[str, list[dict]] = {}
    for column in columns.values():
        # 先用setdefault初始化列表,然后append添加
        grouped.setdefault(column["table_id"], []).append(column)

    # ⑤ 每张表补主外键（JOIN 必需，召回通常拿不到）
    table_infos: list[dict] = []
    for table_id, cols in grouped.items():
        names = {c["name"] for c in cols}
        for key in await meta.get_key_columns(dataset_id, table_id):
            if key.name not in names:
                cols.append(
                    {
                        "id": key.id,
                        "table_id": key.table_id,
                        "name": key.name,
                        "type": key.type,
                        "role": key.role,
                        "description": key.description,
                        "examples": key.examples,
                        "alias": key.alias,
                    }
                )
        # 进 prompt 的 examples 只留前 3 个（ES 里仍是全量，用于值召回）
        trimmed_cols = [
            {**column, "examples": (column.get("examples") or [])[:3]} for column in cols
        ]
        table_infos.append(
            {
                "name": table_id,
                "role": "dim" if table_id.startswith("dim") else "fact",
                "description": "",
                "columns": trimmed_cols,
            }
        )


    # ⑥ 表间关系：没有真实外键约束，用 LLM 看 role + examples 推断
    relations: list[str] = []
    foreign_keys: list[dict] = []
    primary_keys: list[dict] = []
    for table in table_infos:
        for column in table["columns"]:
            item = {
                "column": f"{table['name']}.{column['name']}",
                "type": column.get("type", ""),
                "examples": (column.get("examples") or [])[:3],
            }
            if column.get("role") == "foreign_key":
                foreign_keys.append(item)
            elif column.get("role") == "primary_key":
                primary_keys.append(item)

    # 只有一个表或没有外键就不花这次 token
    if foreign_keys and primary_keys and len(table_infos) > 1:
        try:
            relations = await infer_relations(foreign_keys, primary_keys)
        except Exception as exc:  # noqa: BLE001 - 推断失败不影响主流程
            logger.warning(f"关系推断失败，跳过：{exc}")
            relations = []
    # metrics
    metrics = [
        {
            "name": m["name"],
            "description": m.get("description", ""),
            "relevant_columns": m.get("relevant_columns", []),
            "alias": m.get("alias", []),
        }
        for m in state.get("retrieved_metric_infos", [])
    ]

    runtime.stream_writer({"type": "progress", "step": "合并召回", "status": "success"})
    return {
        "table_infos": table_infos,
        "metric_infos": metrics,
        "matched_values": matched,
        "table_relations": sorted(set(relations)),
    }
