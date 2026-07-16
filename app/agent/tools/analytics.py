from pydantic_ai import ModelRetry, RunContext

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.analytics import compute_summary, resolve_day_bounds


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
