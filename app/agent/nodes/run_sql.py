"""只读执行 SQL，结果通过流推给前端。"""

from datetime import date, datetime
from decimal import Decimal

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


def _jsonable(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


async def run_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "执行SQL", "status": "running"})
    rows = await runtime.context["source"].execute(state.get("sql", ""), limit=1000)
    rows = [_jsonable(r) for r in rows]
    runtime.stream_writer({"type": "progress", "step": "执行SQL", "status": "success"})
    # result 帧统一在 write_cache 发送（自检之后），避免重试时重复推送
    return {"rows": rows}
