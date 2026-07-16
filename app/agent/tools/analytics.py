from pydantic_ai import ModelRetry, RunContext

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.analytics import (
    compute_daily_breakdown,
    compute_summary,
    resolve_day_bounds,
)


@agent.tool(sequential=True)
async def get_sales_summary(ctx: RunContext[AgentDeps], date: str | None = None) -> dict:
    """Closing summary for one day: total sales, CGST/SGST split, cash/UPI/card
    breakdown, bill count, and top 5 items by revenue.

    Read-only, computed fresh every call -- nothing is saved. Use this for
    "today's sales?", "how'd we do yesterday?", and "close the day" type
    requests alike; the day's numbers are the same whether asked mid-day or
    at closing time.

    Args:
        date: Day to summarize, YYYY-MM-DD. Defaults to today (IST) if
            omitted.
    """
    try:
        start, end, day = resolve_day_bounds(date)
    except ValueError:
        raise ModelRetry(f"'{date}' isn't a valid date, expected YYYY-MM-DD.")

    summary = await compute_summary(ctx.deps.db, start, end)
    summary["date"] = day.isoformat()
    return summary


@agent.tool(sequential=True)
async def get_sales_trend(
    ctx: RunContext[AgentDeps], start_date: str, end_date: str
) -> dict:
    """Day-by-day sales totals for a date range (inclusive of both ends) --
    for spotting trends or building a trend chart, e.g. this week's sales
    day by day. Only includes days with at least one finalized bill; a day
    with no sales just doesn't appear.

    Args:
        start_date: First day of the range, YYYY-MM-DD.
        end_date: Last day of the range, YYYY-MM-DD (inclusive).
    """
    try:
        start, _, start_day = resolve_day_bounds(start_date)
        _, end, end_day = resolve_day_bounds(end_date)
    except ValueError:
        raise ModelRetry(
            f"'{start_date}' or '{end_date}' isn't a valid date, expected YYYY-MM-DD."
        )
    if start_day > end_day:
        raise ModelRetry("start_date must not be after end_date.")

    breakdown = await compute_daily_breakdown(ctx.deps.db, start, end)
    return {"start_date": start_day.isoformat(), "end_date": end_day.isoformat(), "days": breakdown}
