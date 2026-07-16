from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass
class AgentDeps:
    db: AsyncSession
    chat_id: int
    # set by request_finalize_confirmation() to tell tasks.py to attach
    # Confirm/Cancel buttons to this turn's reply instead of sending it as
    # plain text.
    pending_confirmation: bool = False
