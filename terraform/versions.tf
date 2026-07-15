terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Local state (chosen deliberately -- state file is gitignored).
  # Move to a GCS backend before more than one person touches this.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
