# .env があれば読み込んで環境変数として export する
-include .env
export

REGION ?= asia-northeast1
TF_DIR := infra/terraform/envs/dev

# Terraform へは TF_VAR_* で渡す（tfvars ファイルを手で同期しなくて済む）
export TF_VAR_project_id := $(PROJECT_ID)
export TF_VAR_region := $(REGION)
export TF_VAR_billing_account_id := $(BILLING_ACCOUNT_ID)
export TF_VAR_budget_amount := $(BUDGET_AMOUNT)
export TF_VAR_budget_currency := $(BUDGET_CURRENCY)

.PHONY: help check-env setup lint test bootstrap tf-init tf-plan tf-apply ingest stg eda

help: ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

check-env:
	@test -n "$(PROJECT_ID)" || (echo "PROJECT_ID が未設定です。cp .env.example .env して編集してください" && exit 1)

setup: ## Python 依存関係をインストール
	uv sync

lint: ## ruff と terraform fmt のチェック
	uv run ruff check .
	uv run ruff format --check .
	terraform -chdir=$(TF_DIR) fmt -check -recursive

test: ## ユニットテスト
	uv run pytest -q

# ---- Phase 0: GCP 基盤 ----
bootstrap: check-env ## プロジェクト作成・課金紐付け・tfstate バケット作成（初回のみ）
	./scripts/bootstrap_project.sh

tf-init: check-env ## Terraform 初期化（GCS backend）
	terraform -chdir=$(TF_DIR) init -backend-config="bucket=$(PROJECT_ID)-tfstate" -backend-config="prefix=envs/dev"

tf-plan: check-env ## Terraform plan
	terraform -chdir=$(TF_DIR) plan -out=tfplan

tf-apply: check-env ## Terraform apply（直前の plan を適用）
	terraform -chdir=$(TF_DIR) apply tfplan

# ---- Phase 0: データ ----
ingest: check-env ## Kaggle → GCS raw → BigQuery raw
	uv run python -m recsys.data.ingest_hm

stg: check-env ## raw → stg（型変換・時刻合成・時刻シフト）。REPLAY_START=YYYY-MM-DD で基準日を指定可
	uv run python -m recsys.data.build_stg $(if $(REPLAY_START),--replay-start-wall $(REPLAY_START),)

eda: check-env ## 基本統計を docs/eda/hm_summary.md に出力
	uv run python -m recsys.data.eda --out docs/eda/hm_summary.md
