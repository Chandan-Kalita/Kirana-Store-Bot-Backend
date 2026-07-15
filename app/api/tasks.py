from fastapi import APIRouter, HTTPException, Request

from app.services.core.telegram import send_message
from app.services.helper.settings import get_settings
from app.services.helper.tasks_auth import verify_task_request

router = APIRouter()


@router.post(get_settings().task_handler_path)
async def handle_task(request: Request):
    try:
        verify_task_request(
            request.headers.get("Authorization"),
            expected_audience=str(request.url),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if message is None or "text" not in message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    await send_message(chat_id, f"Got it: {message['text']}")
    return {"ok": True}
