# BigQuery レイヤ（docs/01_architecture.md §3）
locals {
  datasets = {
    raw     = { description = "Kaggle 原本をそのままロード（全列 STRING）", protect = true }
    stg     = { description = "型変換・時刻合成・時刻シフト済み", protect = false }
    feature = { description = "日次スナップショットの user / item 特徴量", protect = false }
    ml      = { description = "学習データ・埋め込み・候補履歴・model manifest", protect = false }
    logs    = { description = "served / user イベント（Pub/Sub BigQuery subscription）", protect = false }
  }
}

resource "google_bigquery_dataset" "this" {
  for_each = local.datasets

  dataset_id  = each.key
  location    = var.region
  description = each.value.description

  # raw 以外は練習の作り直しを楽にするため destroy で中身ごと消せるようにする
  delete_contents_on_destroy = !each.value.protect

  depends_on = [google_project_service.apis]
}
