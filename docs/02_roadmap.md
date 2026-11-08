# 実装ロードマップ

ユーザーが挙げた練習項目との対応は次のとおりです。

| 練習項目 | Phase |
|---|---|
| ① Two-Tower 学習パイプライン | Phase 1〜2 |
| ② Vector Search から Bigtable まで | Phase 3 |
| ③ 推薦 API | Phase 4 |
| ④ リアルタイム Reranker | Phase 5〜6 |

各 Phase には「完了条件」を付けています。条件を満たしてから次へ進みます。

---

## Phase 0: 基盤とデータ（1〜2 日）

**学ぶこと**: Terraform で GCP の土台を作る / GCS と BQ のレイヤ設計 / 時刻シフト

- [x] コード: リポジトリの雛形（uv、ruff、pytest、pre-commit、Makefile）
- [x] コード: Terraform（API の有効化、GCS × 3、BQ データセット × 5、Artifact Registry × 2、サービスアカウント × 5 と最小権限、予算アラート）
- [x] コード: `recsys.data.ingest_hm`（Kaggle → GCS raw → BQ raw）
- [x] コード: `recsys.data.build_stg`（raw → stg。型変換・時刻合成・時刻シフト）
- [x] コード: `recsys.data.eda`（設計判断に必要な基本統計）
- [ ] 実行: 練習専用の GCP プロジェクトを作る（`make bootstrap`）
- [ ] 実行: `make tf-init tf-plan tf-apply`
- [ ] 実行: Kaggle の認証を設定し、H&M の規約に同意したうえで `make ingest`
- [ ] 実行: `make stg` → `make eda`。結果を見てリプレイ期間と Phase 1 の学習期間を決める

**完了条件**: `stg.transactions` から合成した時刻つきのデータを引ける。リプレイ期間の日付が決まっている。

---

## Phase 1: Two-Tower をローカルで作る（3〜5 日）

**学ぶこと**: point-in-time で正しい特徴量 / in-batch softmax と logQ 補正 / オフライン評価

- [ ] `recsys.features`: 特徴量の定義と前処理を共通化する。学習と Dataflow で同じコードを使う
- [ ] SQL で `feature.*_daily` と `ml.training_examples` を作る。未来の情報が入らないようにする
- [ ] PyTorch の two-tower を実装する（hash 埋め込み、履歴のプーリング、L2 正規化、temperature、logQ、偽負例のマスク）
- [ ] 評価: 翌日〜7 日の holdout に対する recall@{100,300} を、人気ベースラインと比べる
- [ ] 小さな実験: 次元、学習期間、temperature、logQ の有無

**完了条件**: recall@300 が人気ベースラインをはっきり上回る。結果を `docs/experiments/` に記録している。

---

## Phase 2: 日次学習パイプライン（4〜6 日）→ 練習項目①

**学ぶこと**: KFP v2 / Custom Training / Model Registry / 評価ゲート / Vector Search の blue/green

- [ ] trainer をコンテナにして Artifact Registry に push する
- [ ] KFP コンポーネント: `validate_inputs` → `build_dataset` → `train` → `evaluate` → (Condition) → `register`
- [ ] `embed_items`: GCS（Vector Search 用 JSON）と BQ に出力する
- [ ] Terraform で Index Endpoint を作る。パイプラインには `build_and_deploy_index` / `ann_recall_check` / `promote` / `cleanup` を入れる
- [ ] `active.json` と `ml.model_manifest` で版を管理する
- [ ] スケジュールを登録する（`TZ=Asia/Tokyo 0 3 * * *`）

**完了条件**:
- 2 日連続で自動実行され、active な版が切り替わる
- ゲートで落ちたときに現行の版が維持されることを、わざと失敗させて確かめる

---

## Phase 3: 毎時推論から Bigtable まで（4〜6 日）→ 練習項目②

**学ぶこと**: Dataflow batch と RunInference / FindNeighbors をまとめて投げる方法 / Bigtable のスキーマ・GC・エミュレータ

- [ ] Bigtable エミュレータで `user_candidates` と `user_rt` の読み書きを開発する
- [ ] Terraform で Bigtable インスタンスを作る（無料トライアルを開始するのはここ）
- [ ] Dataflow `retrieve`: ユーザー特徴を読む → user tower → FindNeighbors → Bigtable / BQ に書く
- [ ] 人気順のフォールバックを毎時作る
- [ ] 毎時パイプラインとスケジュールを登録する。版を切り替えた直後は全体を更新する
- [ ] `quality_check` と、BQ のスケジュールクエリによる embedding 監視

**完了条件**: 直近 1 時間にアクティブだったユーザーの 99% 以上が、2 時間以内に作られた候補を持っている。

---

## Phase 4: 推薦 API とイベント基盤（3〜5 日）→ 練習項目③

**学ぶこと**: 非同期 Bigtable クライアント / フォールバックとタイムアウト / Pub/Sub スキーマと BQ subscription / キャッシュ / 負荷試験

- [ ] `rec-api`: 推薦を返す GET、イベントを受ける `/v1/events`、ヘルスチェック
- [ ] Pub/Sub のトピック（スキーマ付き）と BigQuery subscription を作る
- [ ] Cloud Run にデプロイする。サービスアカウントは権限を最小にする
- [ ] Valkey のセッションキャッシュとアイテムメタデータの LRU を入れ、ヒット率をメトリクスで出す
- [ ] Locust か k6 で負荷試験をし、p99 を計測する

**完了条件**:
- 目標の p99 を満たす
- served と user のイベントが `logs.*` に入る
- 候補がない場合と reranker が落ちた場合のフォールバックが、それぞれ動く

---

## Phase 5: リアルタイム特徴と Reranker Phase 1（5〜7 日）→ 練習項目④

**学ぶこと**: Dataflow streaming（イベント時刻・ウォーターマーク・重複排除）/ 既出ペナルティ・Gumbel・DPP・探索枠 / シミュレータによる評価

- [ ] Dataflow `realtime_features`: `user-events` を集計し、Bigtable `user_rt` に `AddToCell` で書く
- [ ] `reranker-api`: Phase 1 の処理を `policy.yaml` で設定し、ユニットテストとベンチマークを書く
- [ ] シミュレータ:
  - `replay`: リプレイ期間の購入を Pub/Sub に流す
  - `sessions`: rec-api を呼び、表示されたアイテムに view を送り、隠れた嗜好に従って click を送る
- [ ] 評価ダッシュボード（BQ）: Jaccard@10、ILS、新規性、シミュレータ上の CTR

**完了条件**:
- 同じユーザーが行動を変えずに続けてアクセスしても、Jaccard@10 が目標値以下になる（例: 0.7）
- シミュレータ上の CTR の悪化が許容範囲に収まる（例: −5% 以内）

> シミュレータのクリックは仮定したモデルから生成したものです。パイプラインの動作確認と相対比較には使えますが、実際のユーザーでの効果を示すものではありません。

---

## Phase 6: 本番化の仕上げ（任意、継続）

- [ ] ML Reranker（LambdaRank）の学習パイプラインと OPE（IPS / DR）
- [ ] A/B テスト: hash による振り分けと、ポリシー YAML の CI での検証
- [ ] CI/CD: GitHub Actions＋Workload Identity Federation で、イメージのビルド、KFP のコンパイル、`terraform plan` を回す
- [ ] SLO とアラート: API の p99、パイプラインの失敗、Dataflow の遅延
- [ ] 発展課題: オンラインの user tower 経路、Procrustes による埋め込みの安定化、画像・テキスト特徴、ILP Reranker

---

## リポジトリ構成（予定）

```
.
├── docs/                      # 調査・設計・ADR・実験記録
├── infra/terraform/           # GCP リソース（envs/dev）
├── src/recsys/                # 共通パッケージ: config, data, sim, sql(テンプレート), features, model …
├── pipelines/
│   ├── training/              # 日次 KFP パイプラインとコンポーネント
│   └── inference/             # 毎時 KFP パイプライン
├── dataflow/
│   ├── retrieve/              # batch: user tower → ANN → Bigtable
│   └── realtime_features/     # streaming: events → Bigtable
├── services/
│   ├── rec_api/
│   └── reranker_api/
├── simulator/
├── scripts/                   # bootstrap などのシェル
└── tests/

SQL は src/recsys/sql/ にパッケージデータとして同梱する。コンテナの中からも同じテンプレートを読めるようにするため。
```
