resource "google_cloud_tasks_queue" "app" {
  depends_on = [google_project_service.apis]

  project  = var.project_id
  name     = var.queue_name
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 10
    max_dispatches_per_second = 5
  }

  retry_config {
    max_attempts  = 5
    min_backoff   = "5s"
    max_backoff   = "300s"
    max_doublings = 4
  }
}

# NOTE: the HTTP target (URL + OIDC token) for a Cloud Tasks queue is set
# per-task by the caller (CreateTask), not on the queue resource itself.
# The app builds task requests against:
#   https://<CLOUD_RUN service URL>${TASK_HANDLER_PATH}
# signed with TASKS_INVOKER_SERVICE_ACCOUNT's OIDC token, audience = that URL.
# See outputs.tf for the deployed service URL (self-referencing, so it's
# only known after the first `apply` -- can't be injected as an env var on
# the same apply that creates the service).
