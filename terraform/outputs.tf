output "cloud_run_url" {
  description = "Deployed Cloud Run service URL. Point Telegram's setWebhook here."
  value       = google_cloud_run_v2_service.app.uri
}

output "artifact_registry_repo" {
  description = "Push images here: <region>-docker.pkg.dev/<project>/<repo>/<image>:<tag>"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "cloud_tasks_queue" {
  description = "Fully-qualified Cloud Tasks queue name."
  value       = google_cloud_tasks_queue.app.id
}

output "run_service_account" {
  description = "Cloud Run runtime service account email."
  value       = google_service_account.run_sa.email
}

output "tasks_invoker_service_account" {
  description = "Service account whose OIDC token Cloud Tasks must attach when calling the task handler."
  value       = google_service_account.tasks_invoker_sa.email
}

output "secret_ids" {
  description = "Secret Manager secret IDs created -- populate their values before first real traffic."
  value       = [for s in google_secret_manager_secret.app_secrets : s.secret_id]
}
