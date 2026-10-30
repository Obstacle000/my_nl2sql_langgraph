"""结果自检：判断“能跑”之外，答案是否合理。"""

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


def _suspect_reason(state: Nl2SqlState) -> str | None:
    rows = state.get("rows") or []
    # ① 空结果：值写错 / 条件过严
    if not rows:
        return "结果为空，可能是筛选值或时间范围写错"
    first = rows[0]
    # ② 全 NULL：join 或字段选错
    if first and all(v is None for v in first.values()):
        return "所有字段为空，可能是 JOIN 条件错误"
    return None


async def check_result(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "检查结果", "status": "running"})
    reason = _suspect_reason(state)
    runtime.stream_writer({"type": "progress", "step": "检查结果", "status": "success"})
    return {"retry_reason": reason, "check_rounds": state.get("check_rounds", 0) + 1}
