# コンテナイメージ（trainer / dataflow / API）
resource "google_artifact_registry_repository" "docker" {
  repository_id = "recsys"
  location      = var.region
  format        = "DOCKER"
  description   = "recsys コンテナイメージ"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}

# コンパイル済み KFP パイプライン（テンプレート）
resource "google_artifact_registry_repository" "kfp" {
  repository_id = "pipelines"
  location      = var.region
  format        = "KFP"
  description   = "Vertex AI Pipelines テンプレート"

  depends_on = [google_project_service.apis]
}
