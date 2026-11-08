# Phase 0 解説: 基盤とデータ

Phase 0 の目的は「後の Phase がすべて乗る土台」を作ることです。中身は次の 3 つです。

1. GCP リソースをコードで管理する仕組み（Terraform）
2. データの置き場所と層の分け方（GCS / BigQuery）
3. 過去データを「今起きていること」として扱うための時間の仕掛け

---

## 1. 実行手順

```bash
# 0) 前提: gcloud の認証（ブラウザが開く）
gcloud auth login
gcloud auth application-default login     # Terraform / Python クライアント用

# 1) 設定
cp .env.example .env                      # PROJECT_ID / BILLING_ACCOUNT_ID を埋める
make setup                                # uv sync

# 2) プロジェクト作成と課金の紐付け（初回のみ）
make bootstrap

# 3) GCP リソースを作る
make tf-init
make tf-plan                              # 何が作られるかを必ず読む
make tf-apply

# 4) データを入れる（Kaggle の規約同意と API トークンの設定が必要）
make ingest                               # 約 3.5GB。回線によっては数十分かかる
make stg                                  # リプレイ初日 = 今日
make eda                                  # docs/eda/hm_summary.md に出力
```

この Phase のコストはほぼゼロです。GCS に数 GB を置き、BQ で数十 GB をスキャンする程度で、無料枠にほぼ収まります。

---

## 2. 何を作ったか、なぜそうしたか

### 2.1 bootstrap と Terraform の分担

| | 担当 | 理由 |
|---|---|---|
| プロジェクト作成、課金の紐付け、tfstate バケット | `scripts/bootstrap_project.sh`（gcloud） | Terraform の state を置く場所は Terraform 自身では作れない（鶏と卵の問題） |
| それ以外の全部 | Terraform（`infra/terraform/envs/dev`） | 作って壊すを繰り返す練習なので、手作業のリソースを残さない |

**ポイント**
- **gcloud のデフォルト設定には触れません。** ほかのプロジェクトでの作業に影響しないよう、ADC の quota project も書き換えません。その代わり、Terraform provider の `billing_project` と `user_project_override` で quota project を指定しています。予算 API はこれがないと 403 になります。
- **値は `TF_VAR_*` で渡します。** Makefile が `.env` の値を環境変数に変換するので、tfvars と `.env` の二重管理になりません。
- **API の有効化は Phase 0 でまとめて済ませます。** 有効化自体は無料で、後の Phase で apply を待つ時間が減ります。また `disable_on_destroy = false` にしています。destroy のときに API が先に無効化されると、ほかのリソースの削除が失敗するからです。

### 2.2 サービスアカウントと最小権限

コンポーネントごとに SA を分けています（pipeline / dataflow / rec-api / reranker / simulator）。権限は**できるだけ小さい単位**で付けます。

| 付ける単位 | 例 |
|---|---|
| プロジェクト | `aiplatform.user`、`bigquery.jobUser` など、プロジェクト単位でしか付けられないもの |
| バケット | dataflow SA は `ml` バケットだけ書き込める |
| データセット | pipeline SA は `raw` を読めるだけで、書き込めない |

Bigtable・Pub/Sub・Cloud Run の権限は、それぞれのリソースを作る Phase で、そのリソース単位で付けます。今の段階で「プロジェクト全体の Bigtable 管理者」のような広い権限を付けてしまわないためです。

> 大規模プロダクトでの意味: SA の鍵が漏れたときの被害範囲を限定できます。「API が Bigtable を書き換えた」といった事故も、権限の時点で起こらなくなります。

### 2.3 データレイヤ

```
Kaggle ──► GCS raw (不変) ──► BQ raw (全列 STRING) ──► BQ stg (型付き・時刻合成済み)
                                                            │
                                         Phase 1 以降: feature ─► ml ─► (Bigtable)
```

| 層 | 方針 | なぜ |
|---|---|---|
| GCS raw | 原本をパス `hm/v1/` に置き、上書きしない（サイズが違えば停止）。バケットはバージョニングを有効にし、`force_destroy=false` | 後段で何が起きても原本から作り直せることが、データ基盤の最後の砦になる |
| BQ raw | **全列 STRING** | CSV の型推定に任せると、`article_id` 先頭の `0` が落ちたり、空文字の扱いがぶれたりする。型の判断は stg で、SQL として明示する |
| BQ stg | 型変換・正規化をして、`event_date` でパーティション | 後段は stg だけを見ればよい。日次の処理はパーティションで絞り込むので安い |

`ml` バケットの lifecycle では、**モデルは年齢で自動削除しません**。学習が 1 か月失敗し続けた場合、active なモデルは 1 か月前のものになります。年齢で消すと本番が壊れます。自動で消すのは `pipeline_root/` と `tmp/` だけです。

### 2.4 時間の仕掛け（このプロジェクト特有で、一番大事なところ）

H&M のデータは 2018〜2020 年のもので、時刻は**日付しかありません**。そのままでは次のことができません。

- 「毎時、直近 1 時間のアクティブユーザーだけ推論する」
- 「リアルタイムでイベントが流れてくる」

そこで stg を作るときに、次の 2 つを行います。

**(a) 日内時刻の合成**（`src/recsys/sim/time_profile.py` と `src/recsys/sql/stg/transactions.sql`）
- 同じ顧客の同じ日の購入を 1 セッションとみなします。セッションの開始時刻は `hash(customer_id, date)` から決め、時間帯の分布は昼と 20〜22 時がピークになる EC の典型的な形にします。
- 各アイテムはセッション開始から 0〜20 分に散らします。
- 時刻を `hash(customer, article)` でアイテムごとに決めると、1 人が 1 日に何時間帯も「アクティブ」になってしまい、毎時の対象人数が実際より膨らみます。それを避けるため、セッション単位で決めています。
- 時間帯の分布は Python 側で 1 回だけ定義し、境界値を SQL に埋め込みます。こうすると分布の定義が二重にならず、テストで「SQL の `RANGE_BUCKET` と同じ結果になること」も確認できます（`tests/test_time_profile.py`）。

**(b) 時刻シフト**（`stg.sim_config`）
- データの最後の 28 日を「リプレイ期間」とします。その初日が「今日」（または指定日）になるよう、すべての時刻を `time_offset_days` 日だけずらします。
- 結果として、**リプレイ初日より前のデータは「過去にあったこと」として BQ に入っている状態**になります。リプレイ期間の分は Phase 5 のシミュレータが「今起きていること」として Pub/Sub に流します。
- 後段のパイプラインは「今がデータセットのいつか」を気にする必要がなく、本物のサービスと同じく `now()` を基準に書けます。これが一番の狙いです。

**取引 ID**: `MD5(customer, article, date, 連番)` から決定的に作ります。Phase 5 でイベントとして流すとき、Pub/Sub の重複配信を取り除くキー（event_id）になります。

---

## 3. 確認ポイント（`make eda` の結果で見るところ）

| 見る指標 | 何に効くか |
|---|---|
| リプレイ期間のアクティブユーザー数（毎時）の p95 | 毎時の FindNeighbors の件数と Dataflow の規模（Phase 3） |
| リピート購入率 | 購入済み商品を Reranker で除外するべきか。H&M はリピートが多いと言われるので、数字で確かめる |
| 上位 1% の商品が購入に占める割合 | logQ 補正と多様化がどれだけ必要か（Phase 1 / 5） |
| ユーザーあたり購入数の分位点 | ユーザーごとのサンプル数の上限 [Y1] |
| 合成した時間帯の分布 | `time_profile` の重みどおりになっているか |
| 結合カバレッジ | 特徴量の欠損率 |

---

## 4. よくあるつまずき

| 症状 | 原因と対処 |
|---|---|
| `make ingest` で 403 | Kaggle のコンペページで規約（Rules）に同意していない |
| `kaggle` コマンドの認証エラー | API トークンを `~/.kaggle/` に置くか、環境変数を設定する（Kaggle のアカウント設定から発行） |
| 予算リソースの作成で 403 | 課金アカウントの権限（Billing Account Administrator / Costs Manager）がない。`.env` の `BILLING_ACCOUNT_ID` を空にすれば、予算以外は作れる |
| `stg.customers` で列が見つからない | 原本の列名がこちらの想定と違う。`raw.customers` のスキーマを確認して SQL を直す |
