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
#   ${SERVICE_URL}${TASK_HANDLER_PATH}
# signed with TASKS_INVOKER_SERVICE_ACCOUNT's OIDC token, audience = that URL.
# SERVICE_URL (var.service_url, see cloud_run.tf) is self-referential -- it's
# "" on the apply that first creates the service. Once deployed, set it from
# `terraform output -raw cloud_run_url` and re-apply.
