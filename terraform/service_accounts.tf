resource "google_service_account" "run_sa" {
  project      = var.project_id
  account_id   = "${var.service_name}-run"
  display_name = "Runtime identity for the ${var.service_name} Cloud Run service"
}

resource "google_service_account" "tasks_invoker_sa" {
  project = var.project_id
  # GCP account_id caps at 30 chars -- "-tasks-invoker" pushed the default
  # service_name past that, so this uses the shorter "-invoker" suffix.
  account_id   = "${var.service_name}-invoker"
  display_name = "Cloud Tasks OIDC identity used to invoke ${var.service_name}"
}

# Runtime SA needs to enqueue tasks onto the queue.
resource "google_project_iam_member" "run_sa_cloudtasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}
