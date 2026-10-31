"""LLM 只做“选择”，程序按选择裁剪原结构。"""

import re

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.question import active_question
from app.agent.state import Nl2SqlState
from app.prompt.prompt_loader import load_prompt


async def filter_table(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "running"})
    table_infos = state.get("table_infos", [])
    if not table_infos:
        runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
        return {"table_infos": []}

    # 短路：只有一张表时没有"选哪张表"的问题，字段已由 merge 收窄过
    # （召回字段 + 主外键 + 日期列），直接跳过这次 LLM 调用
    if len(table_infos) == 1:
        runtime.stream_writer(
            {"type": "progress", "step": "过滤表信息", "status": "success", "skipped": True}
        )
        return {"table_infos": table_infos}

    prompt = PromptTemplate(
        template=load_prompt("filter_table_info"),
        input_variables=["question", "table_infos"],
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        result = await chain.ainvoke(
            {
                "question": active_question(state),
                "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
            }
        )
    except Exception:  # noqa: BLE001 - 模型输出不可控，解析失败就降级
        # 解析失败就不过滤，宁可多给上下文
        runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
        return {"table_infos": table_infos}

    # 指标依赖的字段必须保留：否则表达式里的字段被裁掉，模型只能改口径
    metric_columns: set[str] = set()
    metric_tables: set[str] = set()
    for metric in (state.get("retrieved_metric_infos") or []) + (state.get("metric_infos") or []):
        for column_id in metric.get("relevant_columns") or []:
            text = str(column_id)
            metric_columns.add(text)                    # 26:t_ord.amt
            simple = text.split(":", 1)[-1]             # t_ord.amt
            metric_columns.add(simple)
            if "." in simple:
                metric_tables.add(simple.split(".", 1)[0])

    # 问题里提到时间时，日期类字段必须保留：
    # 否则模型没有日期列可用，会把时间条件硬套到订单号上
    has_time_word = bool(
        re.search(r"\d{4}\s*年|\d{1,2}\s*月|\d{1,2}\s*日|今天|昨天|本周|本月|上周|上个月|季度", active_question(state))
    )
    date_like = re.compile(r"date|dt|time|day|month|year", re.IGNORECASE)

    kept: list[dict] = []
    for table in table_infos:
        # 指标依赖的表即使 LLM 没选也要保留
        if table["name"] not in result and table["name"] not in metric_tables:
            continue
        wanted = set(result.get(table["name"], []))
        table = dict(table)
        table["columns"] = [
            column
            for column in table["columns"]
            if column["name"] in wanted
            or column.get("id") in metric_columns
            or f"{table['name']}.{column['name']}" in metric_columns
            or (has_time_word and date_like.search(column["name"]))
        ]
        if table["columns"]:
            kept.append(table)

    runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
    return {"table_infos": kept or table_infos}
