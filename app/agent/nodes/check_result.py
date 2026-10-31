"""结果自检：判断“能跑”之外，答案是否合理。

规则命中 → 返回 retry_reason → 图里路由回 correct_sql 重试一次。
纯正则，零 token；规则要少而准，误报会多花一次 LLM 调用。
"""

import re

from langgraph.runtime import Runtime

from app.agent.context import Nl2SqlContext
from app.agent.state import Nl2SqlState


def _group_by_clause(sql: str) -> str:
    """只取 GROUP BY 子句，避免 WHERE 里的 date_id 干扰判断。"""
    # re 是 Python 标准库 正则表达式（regular expression）模块。
    match = re.search(
        r"group\s+by\s+(.+?)(?:\s+order\s+by|\s+limit|\s+having|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    # 返回droup by后面的字段
    return match.group(1).strip() if match else ""


def _check_daily(question: str, sql: str) -> str | None:
    """① 按天统计：GROUP BY 必须是日期字段。"""
    if not re.search(r"每天|每日|按天|按日|逐日", question):
        return None
    group = _group_by_clause(sql)
    if not group:
        return "问句要求按天统计，但 SQL 没有 GROUP BY"
    # GROUP BY 里有没有日期类字段?
    if not re.search(r"date_id|order_date|[\w.]*_date\b|[\w.]*_dt\b|\bdt\b|datetime|\bdate\b", group, re.IGNORECASE):
        return (
            f"问句要求按天统计，但 GROUP BY 用的是 {group[:40]}，"
            "不是日期字段（应按日期编号 date_id 分组）"
        )
    return None


def _check_ranking(question: str, sql: str) -> str | None:
    """② 极值/排名：必须先分组聚合，再 ORDER BY（必要时 LIMIT）。"""
    if not re.search(r"最低|最高|最多|最少|第一|top\s*\d|排名", question, re.IGNORECASE):
        return None
    lowered = sql.lower()
    if ("min(" in lowered or "max(" in lowered) and "group by" not in lowered:
        return (
            "问的是分组后的极值/排名，应先 GROUP BY 聚合再排序，"
            "不能直接对明细列取 MIN/MAX"
        )
    if "group by" in lowered and "order by" not in lowered:
        return "分组比较类问题缺少 ORDER BY（以及 LIMIT 1）"
    return None

# 比例类问题的结果不应该大于 100
def _check_ratio(question: str, rows: list[dict]) -> str | None:
    """③ 比例类：结果应该在合理范围（0~1 或 0~100）。"""
    if not re.search(r"占比|比例|率", question):
        return None
    for row in rows:
        for value in row.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 100:
                return "问的是比例，但结果大于 100，可能没有除以总数"
    return None


def _check_time_empty(question: str, rows: list[dict]) -> str | None:
    """④ 有时间条件却结果为空：多半是日期字段用法错。"""
    if rows:
        return None
    if re.search(r"20\d{2}\s*年|20\d{2}-\d{2}", question):
        return (
            "结果为空，检查时间条件：date_id 是 yyyyMMdd 整数，"
            "应按 year/month 过滤，或用 date_id = 20250101"
        )
    return None


DATE_LIKE = re.compile(r"date|dt|time|day|month|year", re.IGNORECASE)
DATE_TYPES = ("date", "datetime", "timestamp", "time")


def _is_date_column(column: str, types: dict[str, str] | None = None) -> bool:
    """优先看字段类型，类型拿不到或存的是整数日期编号时再看名字。"""
    column_type = (types or {}).get(column.lower(), "").lower()
    if any(token in column_type for token in DATE_TYPES):
        return True
    return bool(DATE_LIKE.search(column))


def _check_time_on_wrong_column(
    question: str, sql: str, rows: list[dict], column_types: dict[str, str] | None = None
) -> str | None:
    """⑤ 时间条件作用在非日期字段上，或聚合结果恒为 0。"""
    has_time_word = bool(re.search(r"20\d{2}\s*年|20\d{2}-\d{2}|20\d{6}", question))
    if not has_time_word:
        return None

    # 对编号类字段用日期函数：STR_TO_DATE(ord_no...) / DATE_FORMAT(order_no...)
    for func, column in re.findall(
        # 列名可能是 a.b 形式，用非捕获组吃掉表前缀，group2 才是完整列名
        r"(STR_TO_DATE|DATE_FORMAT|DATE|YEAR|MONTH|DAY)\s*\(\s*(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)",
        sql,
        re.IGNORECASE,
    ):
        if _is_date_column(column, column_types):
            continue
        return (
            f"对非日期字段 {column} 使用了日期函数 {func.upper()}，"
            "时间条件应该作用在日期字段上（如 dt / date_id）"
        )

    # 与日期字面量比较的列：WHERE t_ord.ord_no >= '2025-01-01' / LIKE '202501%'
    comparisons = re.findall(
        r"([A-Za-z_][\w]*)\s*(?:=|>=|<=|>|<|like)\s*'?20\d{2}", sql, re.IGNORECASE
    )
    for column in comparisons:
        # 类型是日期（或名字像日期）就不算错
        if _is_date_column(column, column_types):
            continue
        return (
            f"时间条件作用在非日期字段 {column} 上，"
            "应该用日期字段做范围过滤（如 dt BETWEEN 20250101 AND 20250131）"
        )

    # 聚合结果只有一行且为 0：多半是过滤条件打在了错误的字段上
    values = [value for row in rows for value in row.values()]
    if len(values) == 1 and isinstance(values[0], (int, float)) and float(values[0]) == 0:
        return "聚合结果为 0，检查时间/筛选条件是否作用在正确的字段上"
    return None


def _suspect_reason(
    state: Nl2SqlState, column_types: dict[str, str] | None = None
) -> str | None:
    rows = state.get("rows") or []
    question = state.get("question", "")
    sql = state.get("sql", "")

    # 原有两条：空结果 / 全 NULL
    if not rows:
        return "结果为空，可能是筛选值或时间范围写错"
    first = rows[0]
    if first and all(v is None for v in first.values()):
        return "所有字段为空，可能是 JOIN 条件错误"

    for reason in (
        _check_daily(question, sql),
        _check_ranking(question, sql),
        _check_ratio(question, rows),
        _check_time_empty(question, rows),
        _check_time_on_wrong_column(question, sql, rows, column_types),
    ):
        if reason:
            return reason
    return None


async def check_result(state: Nl2SqlState, runtime: Runtime[Nl2SqlContext]) -> dict:
    runtime.stream_writer({"type": "progress", "step": "检查结果", "status": "running"})
    # 从元数据取"哪些列是日期列"，用于判断时间条件是否打在非日期字段上
    column_types: dict[str, str] = {}
    try:
        ctx = runtime.context
        columns = await ctx["meta_repo"].list_columns(ctx["dataset_id"])
        column_types = {col.name.lower(): (col.type or "") for col in columns}
    except Exception:  # noqa: BLE001 - 取不到元数据就退化成按名字判断
        column_types = {}

    reason = _suspect_reason(state, column_types)
    runtime.stream_writer({"type": "progress", "step": "检查结果", "status": "success"})
    return {"retry_reason": reason, "check_rounds": state.get("check_rounds", 0) + 1}
