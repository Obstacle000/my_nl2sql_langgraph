"""指标过滤：LLM 选名字，程序裁剪。"""

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.state import Nl2SqlState
from app.prompt.prompt_loader import load_prompt


async def filter_metric(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "过滤指标", "status": "running"})
    metrics = state.get("metric_infos", [])
    if not metrics:
        runtime.stream_writer({"type": "progress", "step": "过滤指标", "status": "success"})
        return {"metric_infos": []}

    prompt = PromptTemplate(
        template=load_prompt("filter_metric_info"),
        input_variables=["question", "metric_infos"],
    )
    chain = prompt | llm | JsonOutputParser()
    try:
        names = await chain.ainvoke(
            {
                "question": state["question"],
                "metric_infos": yaml.dump(metrics, allow_unicode=True, sort_keys=False),
            }
        )
    except Exception:  # noqa: BLE001 - 模型输出不可控，解析失败就降级
        runtime.stream_writer({"type": "progress", "step": "过滤指标", "status": "success"})
        return {"metric_infos": metrics}

    if not isinstance(names, list):
        names = []
    kept = [m for m in metrics if m["name"] in names]
    runtime.stream_writer({"type": "progress", "step": "过滤指标", "status": "success"})
    return {"metric_infos": kept}
