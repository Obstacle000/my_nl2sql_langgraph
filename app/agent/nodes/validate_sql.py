"""校验 SQL：EXPLAIN；失败写 error，由条件边决定是否修正。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


async def validate_sql(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "校验SQL", "status": "running"})
    sql = state.get("sql") or ""
    if not sql.strip():
        runtime.stream_writer({"type": "progress", "step": "校验SQL", "status": "success"})
        return {"error": "模型没有产出 SQL"}

    try:
        await runtime.context["source"].validate(sql)
    except Exception as exc:  # noqa: BLE001 - 数据库错误类型多
        runtime.stream_writer({"type": "progress", "step": "校验SQL", "status": "success"})
        return {"error": str(exc)}

    runtime.stream_writer({"type": "progress", "step": "校验SQL", "status": "success"})
    return {"error": None}
