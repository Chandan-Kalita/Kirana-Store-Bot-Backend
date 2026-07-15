import hmac

from fastapi import APIRouter, HTTPException, Request

from app.services.core.cloud_tasks import enqueue_update
from app.services.helper.settings import get_settings

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not hmac.compare_digest(secret or "", get_settings().webhook_secret):
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    update = await request.json()
    # Hand off to Cloud Tasks and return immediately -- Telegram expects a
    # fast 200 or it'll consider the update undelivered and redeliver it.
    enqueue_update(update)
    return {"ok": True}
