"""按错误重写 SQL，返回 fix_rounds+1（回到校验节点）。"""

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.llm import llm
from app.agent.nodes.generate_sql import clean_sql
from app.agent.question import active_question
from app.agent.state import Nl2SqlState
from app.prompt.prompt_loader import load_prompt


async def correct_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "修正SQL", "status": "running"})
    prompt = PromptTemplate(
        template=load_prompt("correct_sql"),
        input_variables=["question", "table_infos", "sql", "error"],
    )
    chain = prompt | llm | StrOutputParser()
    fixed = await chain.ainvoke(
        {
            "question": active_question(state),
            "table_infos": yaml.dump(
                state.get("table_infos", []), allow_unicode=True, sort_keys=False
            ),
            "sql": state.get("sql", ""),
            "error": state.get("error") or state.get("retry_reason") or "",
        }
    )
    runtime.stream_writer({"type": "progress", "step": "修正SQL", "status": "success"})
    return {
        "sql": clean_sql(fixed),
        "error": None,
        "retry_reason": None,
        "fix_rounds": state.get("fix_rounds", 0) + 1,
    }
