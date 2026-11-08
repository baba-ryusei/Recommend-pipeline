locals {
  labels = {
    env    = "dev"
    system = "recsys-practice"
  }

  # Phase 0 で全部有効化しておく（API 有効化自体は無料。後の Phase で apply 待ちが減る）
  apis = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "bigtable.googleapis.com",
    "bigtableadmin.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "dataflow.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ]
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service = each.value
  # destroy 時に API を無効化すると他リソースの削除が先に失敗することがあるので無効化しない
  disable_on_destroy = false
}
