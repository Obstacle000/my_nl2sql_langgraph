"""补日期与数据库方言信息。"""

from datetime import date

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


async def add_extra_context(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "补充上下文", "status": "running"})
    today = date.today()
    date_info = {
        "date": today.isoformat(),
        "weekday": today.strftime("%A"),
        "quarter": f"Q{(today.month - 1) // 3 + 1}",
    }
    db_info = await runtime.context["source"].db_info()
    runtime.stream_writer({"type": "progress", "step": "补充上下文", "status": "success"})
    return {"date_info": date_info, "db_info": db_info}
