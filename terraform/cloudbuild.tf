data "google_project" "current" {
  project_id = var.project_id
}

locals {
  # Legacy Cloud Build service account -- what 1st-gen GitHub triggers run
  # as by default (no custom service_account set on the trigger below).
  cloudbuild_sa = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = local.cloudbuild_sa
}

resource "google_project_iam_member" "cloudbuild_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = local.cloudbuild_sa
}

# Cloud Build deploys `gcloud run deploy` as run_sa's identity for the
# service -- it needs to be able to act as that runtime SA.
resource "google_service_account_iam_member" "cloudbuild_run_sa_user" {
  service_account_id = google_service_account.run_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = local.cloudbuild_sa
}

# 1st-gen GitHub trigger (github {} block, not the newer Cloud Build v2
# repository_event_config). PREREQUISITE Terraform cannot do for you: the
# Cloud Build GitHub App must already be connected to
# ${var.github_owner}/${var.github_repo} -- Cloud Console > Cloud Build >
# Triggers > Connect Repository > GitHub (Cloud Build GitHub App) >
# authorize > select this repo. That's a one-time manual OAuth step; this
# trigger's `apply` will fail with a "repository not found" style error
# until it's done.
resource "google_cloudbuild_trigger" "deploy_on_push" {
  depends_on = [google_project_service.apis]

  project     = var.project_id
  name        = "${var.service_name}-deploy"
  description = "Build + deploy ${var.service_name} on push to ${var.deploy_branch}"
  filename    = "cloudbuild.yaml"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^${var.deploy_branch}$"
    }
  }
}
