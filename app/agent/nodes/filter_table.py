"""LLM 只做“选择”，程序按选择裁剪原结构。"""

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.state import Nl2SqlState
from app.prompt.prompt_loader import load_prompt


async def filter_table(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "running"})
    table_infos = state.get("table_infos", [])
    if not table_infos:
        runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
        return {"table_infos": []}

    prompt = PromptTemplate(
        template=load_prompt("filter_table_info"),
        input_variables=["question", "table_infos"],
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        result = await chain.ainvoke(
            {
                "question": state["question"],
                "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
            }
        )
    except Exception:  # noqa: BLE001 - 模型输出不可控，解析失败就降级
        # 解析失败就不过滤，宁可多给上下文
        runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
        return {"table_infos": table_infos}

    kept: list[dict] = []
    for table in table_infos:
        if table["name"] not in result:
            continue
        wanted = set(result[table["name"]])
        table = dict(table)
        table["columns"] = [c for c in table["columns"] if c["name"] in wanted]
        if table["columns"]:
            kept.append(table)

    runtime.stream_writer({"type": "progress", "step": "过滤表信息", "status": "success"})
    return {"table_infos": kept or table_infos}
