from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.services.helper.settings import get_settings

_request = google_requests.Request()


def verify_task_request(authorization_header: str | None, expected_audience: str) -> None:
    """Verify the OIDC token Cloud Tasks attaches when it calls the task
    handler. Cloud Run's IAM binding for this service is public (Telegram
    must reach /webhook unauthenticated) and can't be gated per-path, so
    the task handler is responsible for checking this itself."""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise ValueError("missing bearer token")

    token = authorization_header.removeprefix("Bearer ")
    claims = id_token.verify_oauth2_token(token, _request, audience=expected_audience)

    if claims.get("email") != get_settings().tasks_invoker_service_account:
        raise ValueError("unexpected service account")
