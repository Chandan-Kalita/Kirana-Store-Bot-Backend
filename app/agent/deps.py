from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass
class AgentDeps:
    db: AsyncSession
    chat_id: int
    # set by request_finalize_confirmation() -- tells tasks.py to send
    # Confirm/Cancel buttons with the reply instead of plain text
    pending_confirmation: bool = False
