from decimal import Decimal

from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import func
from sqlmodel import select

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.helper.models import Customer, KhataEntry


async def _get_balance(db, customer_id) -> Decimal:
    total = (
        await db.exec(
            select(func.sum(KhataEntry.delta_amount)).where(
                KhataEntry.customer_id == customer_id
            )
        )
    ).one()
    return total if total is not None else Decimal("0")


async def _load_entries(
    db, customer_id, *, limit: int | None = None, ascending: bool = False
) -> list[dict]:
    stmt = select(KhataEntry).where(KhataEntry.customer_id == customer_id)
    stmt = stmt.order_by(
        KhataEntry.created_at.asc() if ascending else KhataEntry.created_at.desc()
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    entries = (await db.exec(stmt)).all()
    return [
        {
            "delta_amount": entry.delta_amount,
            "note": entry.note,
            "created_at": entry.created_at.isoformat(),
        }
        for entry in entries
    ]


MAX_CUSTOMER_PAGE_SIZE = 50


@agent.tool(sequential=True)
async def list_customers(
    ctx: RunContext[AgentDeps], offset: int = 0, limit: int = MAX_CUSTOMER_PAGE_SIZE
) -> dict:
    """List all khata customers, alphabetically, paginated.

    Each customer includes their current balance and their 5 most recent
    khata entries, for a quick browse of who owes what without a separate
    call per customer. Use search_customers instead to resolve one specific
    name.

    Args:
        offset: Number of customers to skip from the start of the list.
        limit: Max customers to return, capped at 50 regardless of the
            value passed.
    """
    if offset < 0:
        raise ModelRetry(f"offset must be >= 0, got {offset}.")
    if limit <= 0:
        raise ModelRetry(f"limit must be positive, got {limit}.")
    limit = min(limit, MAX_CUSTOMER_PAGE_SIZE)

    total = (
        await ctx.deps.db.exec(select(func.count()).select_from(Customer))
    ).one()
    stmt = select(Customer).order_by(Customer.name).offset(offset).limit(limit)
    customers = (await ctx.deps.db.exec(stmt)).all()

    results = []
    for customer in customers:
        balance = await _get_balance(ctx.deps.db, customer.id)
        recent_entries = await _load_entries(ctx.deps.db, customer.id, limit=5)
        results.append(
            {
                "name": customer.name,
                "balance": balance,
                "recent_entries": recent_entries,
            }
        )

    return {
        "total": total,
        "offset": offset,
        "count": len(results),
        "has_more": offset + len(results) < total,
        "customers": results,
    }


@agent.tool(sequential=True)
async def search_customers(ctx: RunContext[AgentDeps], query: str) -> list[dict]:
    """Search khata customers by name, case-insensitive partial match.

    Each result includes the customer's current balance (positive = they
    owe the store, negative = the store owes them). "What's Ramesh's
    balance?" can often resolve straight through this without a separate
    get_balance call, if there's exactly one match.

    Args:
        query: Free-text search term, matched against customer name.
    """
    like = f"%{query}%"
    customers = (
        await ctx.deps.db.exec(select(Customer).where(Customer.name.ilike(like)))
    ).all()
    results = []
    for customer in customers:
        balance = await _get_balance(ctx.deps.db, customer.id)
        results.append({"name": customer.name, "balance": balance})
    return results


@agent.tool(sequential=True)
async def add_credit(
    ctx: RunContext[AgentDeps],
    customer_name: str,
    amount: Decimal,
    note: str | None = None,
) -> dict:
    """Put an amount on a customer's khata (credit given, their debt goes up).

    Looks up the customer by exact name, case-insensitive, and creates them
    if they don't exist yet -- unlike a product, a customer has no price,
    GST, or HSN to invent, just the name the owner typed, so creating one
    on the fly isn't a grounding violation.

    Args:
        customer_name: Customer's name, exact (case-insensitive).
        amount: Amount to add to their debt. Must be positive.
        note: Optional note, e.g. what was bought or why.
    """
    if amount <= 0:
        raise ModelRetry(f"amount must be positive, got {amount}.")

    customer = (
        await ctx.deps.db.exec(
            select(Customer).where(func.lower(Customer.name) == customer_name.lower())
        )
    ).first()
    if customer is None:
        customer = Customer(name=customer_name)
        ctx.deps.db.add(customer)
        await ctx.deps.db.flush()

    ctx.deps.db.add(
        KhataEntry(customer_id=customer.id, delta_amount=amount, note=note)
    )
    await ctx.deps.db.flush()

    balance = await _get_balance(ctx.deps.db, customer.id)
    return {"name": customer.name, "balance": balance}


@agent.tool(sequential=True)
async def record_payment(
    ctx: RunContext[AgentDeps],
    customer_name: str,
    amount: Decimal,
    note: str | None = None,
) -> dict:
    """Record a payment from a customer against their khata.

    Exact-match lookup only, case-insensitive -- never auto-creates. If the
    customer doesn't exist, refuses: don't settle a khata that was never
    opened.

    Args:
        customer_name: Customer's name, exact (case-insensitive).
        amount: Amount paid. Must be positive.
        note: Optional note.
    """
    if amount <= 0:
        raise ModelRetry(f"amount must be positive, got {amount}.")

    customer = (
        await ctx.deps.db.exec(
            select(Customer).where(func.lower(Customer.name) == customer_name.lower())
        )
    ).first()
    if customer is None:
        raise ModelRetry(
            f"No customer named '{customer_name}' on khata. Use search_customers "
            "to check spelling, or add_credit first if they're genuinely new."
        )

    ctx.deps.db.add(
        KhataEntry(customer_id=customer.id, delta_amount=-amount, note=note)
    )
    await ctx.deps.db.flush()

    balance = await _get_balance(ctx.deps.db, customer.id)

    warnings: list[str] = []
    if balance < 0:
        warnings.append(
            f"{customer.name}'s balance is now {balance} -- they've overpaid, "
            "the store owes them."
        )

    return {"name": customer.name, "balance": balance, "warnings": warnings}


@agent.tool(sequential=True)
async def get_balance(ctx: RunContext[AgentDeps], customer_name: str) -> dict:
    """Get one customer's current khata balance and their full entry history.

    Exact-match lookup only, case-insensitive. If there's no exact match,
    use search_customers or list_customers to find the right name first --
    this tool doesn't fuzzy-match.

    Args:
        customer_name: Customer's name, exact (case-insensitive).
    """
    customer = (
        await ctx.deps.db.exec(
            select(Customer).where(func.lower(Customer.name) == customer_name.lower())
        )
    ).first()
    if customer is None:
        raise ModelRetry(
            f"No customer named '{customer_name}' on khata. Use search_customers "
            "or list_customers to find the right name."
        )

    balance = await _get_balance(ctx.deps.db, customer.id)
    entries = await _load_entries(ctx.deps.db, customer.id, ascending=True)

    return {"name": customer.name, "balance": balance, "entries": entries}
