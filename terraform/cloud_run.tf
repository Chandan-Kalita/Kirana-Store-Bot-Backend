resource "google_cloud_run_v2_service" "app" {
  depends_on = [google_project_service.apis]

  project  = var.project_id
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  # Off while the region/config is still being iterated on pre-launch.
  # Worth flipping back to true once this is a live service.
  deletion_protection = false

  template {
    service_account = google_service_account.run_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # Plain, non-secret config.
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.app.name
      }
      env {
        name  = "CLOUD_TASKS_LOCATION"
        value = var.region
      }
      env {
        name  = "TASKS_INVOKER_SERVICE_ACCOUNT"
        value = google_service_account.tasks_invoker_sa.email
      }
      env {
        name  = "TASK_HANDLER_PATH"
        value = var.task_handler_path
      }
      dynamic "env" {
        for_each = var.anthropic_base_url != "" ? [var.anthropic_base_url] : []
        content {
          name  = "ANTHROPIC_BASE_URL"
          value = env.value
        }
      }

      # Secret-backed env vars -- values live in Secret Manager, never in
      # Terraform state or the container spec.
      dynamic "env" {
        for_each = google_secret_manager_secret.app_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    # First apply deploys the placeholder image; real deploys happen via
    # `gcloud run deploy` / CI after you push a real image. Don't let a
    # later `terraform apply` clobber that with the stale default.
    ignore_changes = [template[0].containers[0].image]
  }
}

# Telegram must be able to reach the webhook unauthenticated. The app itself
# is responsible for validating the webhook secret / Cloud Tasks OIDC token
# on incoming requests -- Cloud Run IAM can't gate this per-path.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# The Cloud Tasks invoker SA also needs run.invoker so its OIDC token is
# accepted (belt-and-suspenders with the public binding above; keeps the
# grant correct if ingress is ever locked down later).
resource "google_cloud_run_v2_service_iam_member" "tasks_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.tasks_invoker_sa.email}"
}
