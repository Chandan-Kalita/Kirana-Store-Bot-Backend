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
    """Get a customer's current khata balance and recent activity.

    Exact-match lookup, case-insensitive. If there's no exact match, offers
    close name matches instead of a flat dead end.

    Args:
        customer_name: Customer's name, exact (case-insensitive).
    """
    customer = (
        await ctx.deps.db.exec(
            select(Customer).where(func.lower(Customer.name) == customer_name.lower())
        )
    ).first()
    if customer is None:
        # same ILIKE matcher as search_customers, capped at 5 so the model
        # (or the owner, if it relays these) has concrete candidates with
        # balances to pick from instead of a flat dead end
        close = (
            await ctx.deps.db.exec(
                select(Customer)
                .where(Customer.name.ilike(f"%{customer_name}%"))
                .limit(5)
            )
        ).all()
        if close:
            matches = [
                {"name": c.name, "balance": await _get_balance(ctx.deps.db, c.id)}
                for c in close
            ]
            raise ModelRetry(
                f"No customer named '{customer_name}'. Close matches: {matches}."
            )
        raise ModelRetry(f"No customer named '{customer_name}' on khata.")

    balance = await _get_balance(ctx.deps.db, customer.id)

    recent = (
        await ctx.deps.db.exec(
            select(KhataEntry)
            .where(KhataEntry.customer_id == customer.id)
            .order_by(KhataEntry.created_at.desc())
            .limit(50)
        )
    ).all()

    return {
        "name": customer.name,
        "balance": balance,
        "recent_entries": [
            {
                "delta_amount": entry.delta_amount,
                "note": entry.note,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in recent
        ],
    }
