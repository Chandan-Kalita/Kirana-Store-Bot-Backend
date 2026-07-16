from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.helper.models import Conversation


async def load_history(session: AsyncSession, chat_id: int) -> list[ModelMessage]:
    conversation = await session.get(Conversation, chat_id)
    if conversation is None or not conversation.messages:
        return []
    return ModelMessagesTypeAdapter.validate_python(conversation.messages)


async def save_history(
    session: AsyncSession, chat_id: int, messages: list[ModelMessage]
) -> None:
    dumped = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    conversation = await session.get(Conversation, chat_id)
    if conversation is None:
        conversation = Conversation(chat_id=chat_id, messages=dumped)
    else:
        conversation.messages = dumped
    session.add(conversation)
