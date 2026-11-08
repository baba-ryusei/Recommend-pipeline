# サービスアカウント（コンポーネントごとに分けて最小権限にする）
# Phase 0 では「データ層に触る SA」の権限だけ付ける。Bigtable / Pub/Sub / Cloud Run の権限は
# それぞれのリソースを作る Phase で、リソース単位（インスタンス・トピック単位）に付ける。
locals {
  service_accounts = {
    pipeline  = "Vertex AI Pipelines / Custom Training の実行"
    dataflow  = "Dataflow ワーカー"
    rec-api   = "推薦 API（Cloud Run）"
    reranker  = "Reranker API（Cloud Run）"
    simulator = "ユーザー行動シミュレータ"
  }

  # プロジェクト単位でしか付けられない（or 付けるのが普通な）ロール
  project_roles = {
    pipeline = [
      "roles/aiplatform.user",
      "roles/artifactregistry.reader",
      "roles/bigquery.jobUser",
      "roles/dataflow.developer",
      "roles/logging.logWriter",
    ]
    dataflow = [
      "roles/aiplatform.user", # FindNeighbors
      "roles/artifactregistry.reader",
      "roles/bigquery.jobUser",
      "roles/dataflow.worker",
      "roles/logging.logWriter",
    ]
    rec-api   = ["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"]
    reranker  = ["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"]
    simulator = ["roles/logging.logWriter", "roles/bigquery.jobUser"]
  }

  # バケット単位の権限
  bucket_roles = {
    pipeline = { raw = "roles/storage.objectViewer", ml = "roles/storage.objectAdmin", staging = "roles/storage.objectAdmin" }
    dataflow = { raw = "roles/storage.objectViewer", ml = "roles/storage.objectAdmin", staging = "roles/storage.objectAdmin" }
    rec-api  = { ml = "roles/storage.objectViewer" }
    reranker = { ml = "roles/storage.objectViewer" }
  }

  # データセット単位の権限
  dataset_roles = {
    pipeline  = { raw = "roles/bigquery.dataViewer", stg = "roles/bigquery.dataViewer", feature = "roles/bigquery.dataEditor", ml = "roles/bigquery.dataEditor", logs = "roles/bigquery.dataViewer" }
    dataflow  = { feature = "roles/bigquery.dataViewer", ml = "roles/bigquery.dataEditor", logs = "roles/bigquery.dataViewer" }
    simulator = { stg = "roles/bigquery.dataViewer" }
  }

  project_bindings = flatten([
    for sa, roles in local.project_roles : [for r in roles : { sa = sa, role = r }]
  ])
  bucket_bindings = flatten([
    for sa, m in local.bucket_roles : [for b, r in m : { sa = sa, bucket = b, role = r }]
  ])
  dataset_bindings = flatten([
    for sa, m in local.dataset_roles : [for d, r in m : { sa = sa, dataset = d, role = r }]
  ])
}

resource "google_service_account" "this" {
  for_each = local.service_accounts

  account_id   = "sa-${each.key}"
  display_name = "sa-${each.key}"
  description  = each.value

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "this" {
  for_each = { for b in local.project_bindings : "${b.sa}/${b.role}" => b }

  project = var.project_id
  role    = each.value.role
  member  = google_service_account.this[each.value.sa].member
}

resource "google_storage_bucket_iam_member" "this" {
  for_each = { for b in local.bucket_bindings : "${b.sa}/${b.bucket}/${b.role}" => b }

  bucket = google_storage_bucket.this[each.value.bucket].name
  role   = each.value.role
  member = google_service_account.this[each.value.sa].member
}

resource "google_bigquery_dataset_iam_member" "this" {
  for_each = { for b in local.dataset_bindings : "${b.sa}/${b.dataset}/${b.role}" => b }

  dataset_id = google_bigquery_dataset.this[each.value.dataset].dataset_id
  role       = each.value.role
  member     = google_service_account.this[each.value.sa].member
}

# Pipelines は「パイプラインを実行する SA」として自分自身を、Dataflow ジョブ起動時に dataflow SA を使う
resource "google_service_account_iam_member" "pipeline_act_as" {
  for_each = toset(["pipeline", "dataflow"])

  service_account_id = google_service_account.this[each.value].name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.this["pipeline"].member
}
