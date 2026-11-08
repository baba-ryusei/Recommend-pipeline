# GCS レイヤ（docs/01_architecture.md §3）
#   raw     : Kaggle 原本。不変。誤削除防止にバージョニング＋force_destroy=false
#   ml      : 学習データ・モデル・埋め込み・manifest。モデルは active 版が古くなり得るので年齢で消さない
#   staging : Dataflow / Pipelines の一時領域。7 日で自動削除
locals {
  buckets = {
    raw = {
      versioning    = true
      force_destroy = false
      expire_rules  = []
    }
    ml = {
      versioning    = false
      force_destroy = true
      expire_rules = [
        { prefix = "pipeline_root/", age_days = 30 },
        { prefix = "tmp/", age_days = 7 },
      ]
    }
    staging = {
      versioning    = false
      force_destroy = true
      expire_rules  = [{ prefix = "", age_days = 7 }]
    }
  }
}

resource "google_storage_bucket" "this" {
  for_each = local.buckets

  name                        = "${var.project_id}-${each.key}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = each.value.force_destroy

  versioning {
    enabled = each.value.versioning
  }

  dynamic "lifecycle_rule" {
    for_each = each.value.expire_rules
    content {
      condition {
        age            = lifecycle_rule.value.age_days
        matches_prefix = lifecycle_rule.value.prefix == "" ? null : [lifecycle_rule.value.prefix]
      }
      action {
        type = "Delete"
      }
    }
  }

  depends_on = [google_project_service.apis]
}
