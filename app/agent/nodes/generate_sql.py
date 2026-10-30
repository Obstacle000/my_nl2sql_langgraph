"""生成 SQL：表上下文 + 指标 + 命中值 + 日期/方言 + 原问题 → LLM。"""

import re

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.state import Nl2SqlState
from app.prompt.prompt_loader import load_prompt

_FENCE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.MULTILINE)


def clean_sql(text: str) -> str:
    return _FENCE.sub("", text).strip().rstrip(";")


async def generate_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "生成SQL", "status": "running"})
    prompt = PromptTemplate(
        template=load_prompt("generate_sql"),
        input_variables=[
            "question", "table_infos", "metric_infos", "matched_values",
            "table_relations", "date_info", "db_info",
        ],
    )
    chain = prompt | llm | StrOutputParser()
    sql = await chain.ainvoke(
        {
            "question": state["question"],
            "table_infos": yaml.dump(state.get("table_infos", []), allow_unicode=True, sort_keys=False),
            "metric_infos": yaml.dump(state.get("metric_infos", []), allow_unicode=True, sort_keys=False),
            "matched_values": yaml.dump(state.get("matched_values", []), allow_unicode=True, sort_keys=False),
            "table_relations": yaml.dump(state.get("table_relations", []), allow_unicode=True),
            "date_info": yaml.dump(state.get("date_info", {}), allow_unicode=True),
            "db_info": yaml.dump(state.get("db_info", {}), allow_unicode=True),
        }
    )
    runtime.stream_writer({"type": "progress", "step": "生成SQL", "status": "success"})
    return {"sql": clean_sql(sql), "error": None}
