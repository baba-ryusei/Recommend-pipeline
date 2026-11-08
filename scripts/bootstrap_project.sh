#!/usr/bin/env bash
# 練習用 GCP プロジェクトの初期化（初回のみ・冪等）
#   1. プロジェクト作成
#   2. 課金アカウント紐付け
#   3. Terraform 実行に最低限必要な API を有効化
#   4. Terraform state 用バケット作成（バージョニング有効）
#
# Terraform 自身の state を置く場所は Terraform で作れない（鶏と卵）ので、ここだけ gcloud で作る。
# gcloud のデフォルト設定（active configuration / ADC の quota project）は変更しない。
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID を .env に設定してください}"
: "${BILLING_ACCOUNT_ID:?BILLING_ACCOUNT_ID を .env に設定してください}"
REGION="${REGION:-asia-northeast1}"
STATE_BUCKET="gs://${PROJECT_ID}-tfstate"

echo "==> project: ${PROJECT_ID} / region: ${REGION}"

if gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "    project already exists"
else
  gcloud projects create "${PROJECT_ID}" --name="recsys-practice"
fi

echo "==> link billing account"
gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT_ID}"

echo "==> enable bootstrap APIs"
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  cloudbilling.googleapis.com \
  billingbudgets.googleapis.com \
  iam.googleapis.com \
  storage.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> terraform state bucket"
if gcloud storage buckets describe "${STATE_BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "    ${STATE_BUCKET} already exists"
else
  gcloud storage buckets create "${STATE_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
gcloud storage buckets update "${STATE_BUCKET}" --versioning --project="${PROJECT_ID}"

echo "==> done. next: make tf-init && make tf-plan"
