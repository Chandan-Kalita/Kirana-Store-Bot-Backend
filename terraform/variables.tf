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
