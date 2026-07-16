import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent import agent
from app.agent.conversation import load_history, save_history
from app.agent.deps import AgentDeps
from app.agent.tools.bills import finalize_confirmed_bill
from app.services.core.telegram import (
    answer_callback_query,
    edit_message_text,
    send_message,
    send_message_with_confirm_buttons,
)
from app.services.helper.db import get_session
from app.services.helper.models import Conversation, ConversationArchive
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

    callback = update.get("callback_query")
    if callback is not None:
        await _handle_finalize_callback(session, callback)
        return {"ok": True}

    message = update.get("message") or update.get("edited_message")
    if message is None or "text" not in message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message["text"]

    if text.strip() == "/new":
        conversation = await session.get(Conversation, chat_id)
        if conversation is not None:
            session.add(
                ConversationArchive(chat_id=chat_id, messages=conversation.messages)
            )
            await session.delete(conversation)
            await session.commit()
        await send_message(chat_id, "Started a new conversation.")
        return {"ok": True}

    history = await load_history(session, chat_id)
    deps = AgentDeps(db=session, chat_id=chat_id)
    try:
        result = await agent.run(text, message_history=history, deps=deps)
    except Exception:
        logger.exception("agent.run failed for chat_id=%s", chat_id)
        await send_message(
            chat_id, "Something went wrong on my end. Please try again."
        )
        return {"ok": True}

    await save_history(session, chat_id, result.all_messages())
    await session.commit()

    if deps.pending_confirmation:
        await send_message_with_confirm_buttons(chat_id, result.output)
    else:
        await send_message(chat_id, result.output)
    return {"ok": True}


async def _handle_finalize_callback(session: AsyncSession, callback: dict) -> None:
    """Handle a tap on the Confirm/Cancel buttons -- entirely outside the
    agent loop. The LLM proposed the bill; only this deterministic path can
    actually finalize it."""
    await answer_callback_query(callback["id"])

    data = callback.get("data", "")
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]

    if data == "fin:cancel":
        await edit_message_text(
            chat_id, message_id, "Not finalized. Bill is still open."
        )
        return

    if data != "fin:confirm":
        return

    try:
        outcome = await finalize_confirmed_bill(session, chat_id)
        await session.commit()
    except Exception:
        logger.exception("finalize_confirmed_bill failed for chat_id=%s", chat_id)
        await session.rollback()
        await edit_message_text(
            chat_id, message_id, "Something went wrong finalizing. Please try again."
        )
        return

    if not outcome["ok"]:
        await edit_message_text(
            chat_id, message_id, f"Not finalized: {outcome['message']}"
        )
        return

    if outcome.get("already_finalized"):
        await edit_message_text(
            chat_id,
            message_id,
            f"Already finalized. Total was {outcome['total_amount']}.",
        )
        return

    lines = [f"{i['name']} x {i['qty']} = {i['line_total']}" for i in outcome["items"]]
    await edit_message_text(
        chat_id,
        message_id,
        "Bill finalized.\n"
        + "\n".join(lines)
        + f"\nTotal: {outcome['total_amount']} ({outcome['payment_mode']})",
    )
