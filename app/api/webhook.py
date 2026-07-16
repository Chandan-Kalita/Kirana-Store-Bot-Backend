import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from app.services.core.cloud_tasks import enqueue_update
from app.services.core.telegram import answer_callback_query, edit_message_text
from app.services.helper.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not hmac.compare_digest(secret or "", get_settings().webhook_secret):
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    update = await request.json()

    callback = update.get("callback_query")
    if callback is not None:
        await _ack_callback(callback)

    # Hand off to Cloud Tasks and return immediately -- Telegram expects a
    # fast 200 or it'll consider the update undelivered and redeliver it.
    enqueue_update(update)
    return {"ok": True}


async def _ack_callback(callback: dict) -> None:
    """Answer a button tap right here, before the Cloud Tasks round trip --
    tasks.py doing it after the queue hop was slow enough that taps looked
    ignored. Best-effort, shouldn't block the enqueue below."""
    try:
        await answer_callback_query(callback["id"])
        if callback.get("data") == "fin:confirm":
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            if "message_id" in message and "id" in chat:
                await edit_message_text(
                    chat["id"], message["message_id"], "⏳ Finalizing..."
                )
    except Exception:
        logger.exception("failed to ack callback_query %s", callback.get("id"))
