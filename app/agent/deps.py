from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass
class AgentDeps:
    db: AsyncSession
    chat_id: int
