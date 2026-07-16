import re

import httpx

from app.services.helper.settings import get_settings

TELEGRAM_API_BASE = "https://api.telegram.org"

# belt-and-suspenders: the system prompt already tells the model not to use
# markdown (messages are sent plain, no parse_mode), but strip the common
# markers here too in case it slips one in. Only strips paired markers
# around actual content, so a bare "_" in a SKU or UPI ref is left alone.
_MARKDOWN_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # **bold**
    (re.compile(r"__(.+?)__"), r"\1"),  # __bold__
    (re.compile(r"~~(.+?)~~"), r"\1"),  # ~~strikethrough~~
    (re.compile(r"`(.+?)`"), r"\1"),  # `code`
    (re.compile(r"\*(.+?)\*"), r"\1"),  # *italic*
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),  # # headings
]


def _sanitize(text: str) -> str:
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# no bill id in callback_data -- a chat only ever has one draft, so "the
# current draft for this chat" is enough on tap
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
            _bot_url("sendMessage"), json={"chat_id": chat_id, "text": _sanitize(text)}
        )
        resp.raise_for_status()


async def send_message_with_confirm_buttons(chat_id: int | str, text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            _bot_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": _sanitize(text),
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
            json={"chat_id": chat_id, "message_id": message_id, "text": _sanitize(text)},
        )
        resp.raise_for_status()
