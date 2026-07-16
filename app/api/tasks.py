import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.conversation import load_history, save_history
from app.agent.core import agent
from app.agent.deps import AgentDeps
from app.services.core.telegram import send_message
from app.services.helper.db import get_session
from app.services.helper.models import Conversation
from app.services.helper.settings import get_settings
from app.services.helper.tasks_auth import verify_task_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(get_settings().task_handler_path)
async def handle_task(
    request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        verify_task_request(
            request.headers.get("Authorization"),
            expected_audience=get_settings().task_handler_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if message is None or "text" not in message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message["text"]

    if text.strip() == "/new":
        conversation = await session.get(Conversation, chat_id)
        if conversation is not None:
            await session.delete(conversation)
            await session.commit()
        await send_message(chat_id, "Started a new conversation.")
        return {"ok": True}

    history = await load_history(session, chat_id)
    try:
        result = await agent.run(
            text, message_history=history, deps=AgentDeps(db=session, chat_id=chat_id)
        )
    except Exception:
        logger.exception("agent.run failed for chat_id=%s", chat_id)
        await send_message(
            chat_id, "Something went wrong on my end. Please try again."
        )
        return {"ok": True}

    await save_history(session, chat_id, result.all_messages())
    await session.commit()

    await send_message(chat_id, result.output)
    return {"ok": True}
