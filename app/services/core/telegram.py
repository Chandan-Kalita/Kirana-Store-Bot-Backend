import httpx

from app.services.helper.settings import get_settings

TELEGRAM_API_BASE = "https://api.telegram.org"

# Confirm/Cancel keyboard attached to the finalize-confirmation message --
# callback_data stays short and doesn't carry a bill id: a chat can have at
# most one draft bill at a time, so "the current draft for this chat" is
# enough to resolve on tap.
_FINALIZE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "✅ Confirm", "callback_data": "fin:confirm"},
            {"text": "❌ Cancel", "callback_data": "fin:cancel"},
        ]
    ]
}


def _bot_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{get_settings().telegram_bot_token}/{method}"


async def send_message(chat_id: int | str, text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("sendMessage"), json={"chat_id": chat_id, "text": text}
        )
        resp.raise_for_status()


async def send_message_with_confirm_buttons(chat_id: int | str, text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": _FINALIZE_KEYBOARD,
            },
        )
        resp.raise_for_status()


async def answer_callback_query(callback_query_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("answerCallbackQuery"),
            json={"callback_query_id": callback_query_id},
        )
        resp.raise_for_status()


async def edit_message_text(chat_id: int | str, message_id: int, text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("editMessageText"),
            json={"chat_id": chat_id, "message_id": message_id, "text": text},
        )
        resp.raise_for_status()
