from pydantic_ai import RunContext
from sqlmodel import select

from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.helper.models import Preference, PreferenceKey


@agent.tool(sequential=True)
async def set_preference(
    ctx: RunContext[AgentDeps], key: PreferenceKey, value: str
) -> dict:
    """Remember a standing shop preference, across chats and across /new.

    Call this the moment the owner states something that sounds like a
    standing rule ("always assume UPI unless I say cash", "default atta is
    Aashirvaad 5kg", "our GSTIN is X") -- don't just carry it in
    conversation, it needs to survive /new and other chats.

    Args:
        key: Which preference this is.
        value: The value to remember, as free text (e.g. a payment mode, a
            SKU, a shop name, a GSTIN).
    """
    existing = await ctx.deps.db.get(Preference, key)
    if existing is None:
        ctx.deps.db.add(Preference(key=key, value=value))
    else:
        existing.value = value
        ctx.deps.db.add(existing)
    await ctx.deps.db.flush()
    return {"key": key, "value": value}


@agent.tool(sequential=True)
async def get_preference(ctx: RunContext[AgentDeps], key: PreferenceKey) -> dict:
    """Look up one standing shop preference.

    Call this before asking a clarifying question a preference could
    already answer -- e.g. check default_atta_sku before asking "which
    atta?", or default_payment_mode before asking how the owner is paying.

    Args:
        key: Which preference to look up.
    """
    pref = await ctx.deps.db.get(Preference, key)
    return {"key": key, "value": pref.value if pref else None}


@agent.tool(sequential=True)
async def list_preferences(ctx: RunContext[AgentDeps]) -> list[dict]:
    """List every standing preference currently set.

    Useful for "what do you remember about me/the shop" and for sanity-
    checking before assuming nothing's been set yet.
    """
    prefs = (await ctx.deps.db.exec(select(Preference))).all()
    return [{"key": p.key, "value": p.value} for p in prefs]
