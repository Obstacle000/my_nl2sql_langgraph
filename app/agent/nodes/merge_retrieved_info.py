import re

"""合并三路召回：去重 → 补指标依赖字段 → 命中值标注 → 补主外键 → 按表聚合。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


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
        # 日期类字段必补：召回经常漏掉 dt/date_id，而时间过滤必须用它
        existing = {c["name"] for c in cols}
        for column in await meta.list_columns_by_table(dataset_id, table_id):
            if column.name in existing:
                continue
            if not re.search(r"date|dt|time|day|month|year", column.name, re.IGNORECASE):
                continue
            cols.append(
                {
                    "id": column.id,
                    "table_id": column.table_id,
                    "name": column.name,
                    "type": column.type,
                    "role": column.role,
                    "description": column.description,
                    "examples": column.examples,
                    "alias": column.alias,
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


    # ⑥ 表间关系：建源时已推断并存入 table_relation，这里直接读（不再每次调 LLM）
    relations = await meta.list_relations(dataset_id)

    # metrics
    metrics = [
        {
            "name": m["name"],
            "description": m.get("description", ""),
            "expression": m.get("expression", ""),
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
