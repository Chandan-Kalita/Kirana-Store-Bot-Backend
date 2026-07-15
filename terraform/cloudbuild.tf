data "google_project" "current" {
  project_id = var.project_id
}

# Cloud Build's build-time validation rejects explicitly naming the legacy
# PROJECT_NUMBER@cloudbuild.gserviceaccount.com SA on a trigger ("provide a
# user-managed service account or leave unset") -- but 2nd-gen triggers
# (repository_event_config below) require *some* explicit service_account
# or trigger creation itself 400s. So: a real user-managed SA, standing in
# for what the legacy default used to grant implicitly.
resource "google_service_account" "cloudbuild_sa" {
  project      = var.project_id
  account_id   = "${var.service_name}-build"
  display_name = "Cloud Build runtime identity for ${var.service_name} CI"
}

locals {
  cloudbuild_sa = "serviceAccount:${google_service_account.cloudbuild_sa.email}"
}

# User-managed build SAs don't get log-writing for free like the legacy
# default did -- without this, builds fail before running any steps.
resource "google_project_iam_member" "cloudbuild_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = local.cloudbuild_sa
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

# 2nd-gen (Developer Connect-backed) setup. The 1st-gen `github {}` block
# was tried first and abandoned: creating a trigger against the classic
# GitHub App connection returned a bare 400 INVALID_ARGUMENT with zero
# detail from both Terraform and `gcloud` directly, at both global and
# regional locations -- consistent with Google having quietly cut off new
# 1st-gen trigger creation in favor of this flow.
#
# PREREQUISITE Terraform cannot do for you: a 2nd-gen host connection must
# exist first, which requires an interactive OAuth step:
#   gcloud builds connections create github ${var.github_connection_name} \
#     --region=${var.region} --project=${var.project_id}
# This installs the (separate, 2nd-gen) "Google Cloud Build" GitHub App via
# a browser flow -- no PAT involved.
#
# This provider version has no `data` source for google_cloudbuildv2_connection,
# so the connection is modeled as a resource -- but since it's only ever
# created out-of-band (interactively, above), it must be imported rather
# than applied fresh:
#   terraform import google_cloudbuildv2_connection.github \
#     projects/${var.project_id}/locations/${var.region}/connections/${var.github_connection_name}
# (github_config below mirrors what `gcloud builds connections describe`
# reports post-OAuth, so a plan after import shows no diff.)
resource "google_cloudbuildv2_connection" "github" {
  project  = var.project_id
  location = var.region
  name     = var.github_connection_name

  github_config {
    app_installation_id = "146827624"
    authorizer_credential {
      oauth_token_secret_version = "projects/${var.project_id}/secrets/AgenCloudBuild-github-oauthtoken-f5063a/versions/latest"
    }
  }

  lifecycle {
    # OAuth token secret version churns independently (Google rotates it);
    # don't fight that on every plan.
    ignore_changes = [github_config[0].authorizer_credential]
  }
}

resource "google_cloudbuildv2_repository" "app" {
  project           = var.project_id
  location          = var.region
  name              = lower(var.github_repo)
  parent_connection = google_cloudbuildv2_connection.github.id
  remote_uri        = "https://github.com/${var.github_owner}/${var.github_repo}.git"
}

resource "google_cloudbuild_trigger" "deploy_on_push" {
  depends_on = [google_project_service.apis]

  project         = var.project_id
  location        = var.region
  name            = "${var.service_name}-deploy"
  description     = "Build + deploy ${var.service_name} on push to ${var.deploy_branch}"
  filename        = "cloudbuild.yaml"
  service_account = google_service_account.cloudbuild_sa.name

  repository_event_config {
    repository = google_cloudbuildv2_repository.app.id
    push {
      branch = "^${var.deploy_branch}$"
    }
  }
}
