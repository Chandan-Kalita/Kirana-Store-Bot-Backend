resource "google_artifact_registry_repository" "app" {
  depends_on = [google_project_service.apis]

  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repo_id
  format        = "DOCKER"
  description   = "Kirana store agent container images"
}
