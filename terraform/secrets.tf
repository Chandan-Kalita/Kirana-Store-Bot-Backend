locals {
  # Secret Manager secret IDs -- match the keys the app reads via env vars.
  secret_ids = [
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_SECRET",
  ]
}

resource "google_secret_manager_secret" "app_secrets" {
  for_each = toset(local.secret_ids)

  depends_on = [google_project_service.apis]

  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}
  }
}

# Terraform creates the secret containers only. Populate values out-of-band, e.g.:
#   echo -n "<value>" | gcloud secrets versions add DATABASE_URL --data-file=-
# Values never touch .tfvars or terraform.tfstate this way.

resource "google_secret_manager_secret_iam_member" "run_sa_accessor" {
  for_each = google_secret_manager_secret.app_secrets

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run_sa.email}"
}
