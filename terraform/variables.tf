variable "project_id" {
  description = "GCP project ID to deploy into."
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run, Artifact Registry and Cloud Tasks."
  type        = string
  default     = "asia-southeast1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "kirana-store-agent"
}

variable "artifact_repo_id" {
  description = "Artifact Registry Docker repository id."
  type        = string
  default     = "kirana-store"
}

variable "image" {
  description = <<-EOT
    Full container image reference to deploy, e.g.
    asia-southeast1-docker.pkg.dev/<project_id>/kirana-store/kirana-store-agent:latest
    Defaults to Google's public hello-world image so the first `apply`
    succeeds before you've pushed a real image.
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "queue_name" {
  description = "Cloud Tasks queue name."
  type        = string
  default     = "kirana-store-tasks"
}

variable "task_handler_path" {
  description = "Path on the Cloud Run service that Cloud Tasks delivers tasks to."
  type        = string
  default     = "/tasks/handle"
}

variable "service_url" {
  description = <<-EOT
    The Cloud Run service's own https URL, used to build Cloud Tasks targets
    and OIDC audiences. Self-referential -- unknown on the apply that first
    creates the service, so it defaults to "" then. Once deployed, set it
    (e.g. from `terraform output -raw cloud_run_url`) and re-apply.
  EOT
  type        = string
  default     = ""
}

variable "anthropic_base_url" {
  description = "Optional override for the Anthropic API base URL. Empty string means unset."
  type        = string
  default     = ""
}

variable "cpu" {
  description = "Cloud Run container CPU."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Cloud Run container memory."
  type        = string
  default     = "512Mi"
}

variable "min_instances" {
  description = "Cloud Run min instance count (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Cloud Run max instance count."
  type        = number
  default     = 3
}

variable "github_owner" {
  description = "GitHub org/user that owns the source repo for the Cloud Build trigger."
  type        = string
  default     = "Chandan-Kalita"
}

variable "github_repo" {
  description = "GitHub repo name (without owner) for the Cloud Build trigger."
  type        = string
  default     = "Kirana-Store-Bot-Backend"
}

variable "deploy_branch" {
  description = "Branch that triggers a build + deploy on push."
  type        = string
  default     = "master"
}

variable "github_connection_name" {
  description = <<-EOT
    Name of the Cloud Build 2nd-gen GitHub host connection. Must already
    exist -- create it via:
      gcloud builds connections create github <name> --region=<region> --project=<project_id>
    (a one-time interactive OAuth step Terraform can't perform).
  EOT
  type        = string
  default     = "AgenCloudBuild"
}
