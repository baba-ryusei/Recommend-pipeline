variable "project_id" {
  type        = string
  description = "練習用 GCP プロジェクト ID"
}

variable "region" {
  type        = string
  description = "全リソースを置くリージョン（Vector Search / Bigtable / Dataflow を揃える）"
  default     = "asia-northeast1"
}

variable "billing_account_id" {
  type        = string
  description = "予算アラート用の課金アカウント ID。空なら予算は作らない"
  default     = ""
}

variable "budget_amount" {
  type        = number
  description = "月次予算（budget_currency 単位）"
  default     = 10000
}

variable "budget_currency" {
  type        = string
  description = "課金アカウントの通貨コード（JPY / USD など）"
  default     = "JPY"
}
