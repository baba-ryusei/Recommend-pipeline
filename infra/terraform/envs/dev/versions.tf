terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }

  # bucket / prefix は `make tf-init` で -backend-config として渡す（partial configuration）
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region

  # ユーザー認証（ADC）で billingbudgets などを叩くとき、quota project を明示しないと 403 になる。
  # gcloud の ADC 側の quota project を書き換えずに済むよう provider 側で指定する。
  user_project_override = true
  billing_project       = var.project_id

  default_labels = local.labels
}
