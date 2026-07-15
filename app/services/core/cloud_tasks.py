import json
from functools import lru_cache

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.services.helper.settings import get_settings


@lru_cache
def _client() -> tasks_v2.CloudTasksClient:
    return tasks_v2.CloudTasksClient()


def _queue_path() -> str:
    settings = get_settings()
    return _client().queue_path(
        settings.gcp_project,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )


def enqueue_update(update: dict, base_url: str) -> None:
    """Hand a Telegram update off to the task handler via Cloud Tasks.

    base_url comes from the incoming webhook request rather than settings --
    the Cloud Run service URL is self-referential and only known after the
    first deploy (see terraform/cloud_tasks.tf).
    """
    settings = get_settings()
    target_url = base_url.rstrip("/") + settings.task_handler_path
    task: dict = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": target_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(update).encode(),
            "oidc_token": {
                "service_account_email": settings.tasks_invoker_service_account,
                "audience": target_url,
            },
        },
    }

    update_id = update.get("update_id")
    if update_id is not None:
        # Telegram redelivers updates it didn't get a fast 200 for. Naming
        # the task after update_id makes a retried webhook call collapse
        # into the same task instead of double-enqueuing (Cloud Tasks
        # dedupes task names for ~1h after creation/completion).
        task["name"] = f"{_queue_path()}/tasks/update-{update_id}"

    try:
        _client().create_task(parent=_queue_path(), task=task)
    except AlreadyExists:
        pass
