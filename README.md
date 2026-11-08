# Practice-pipeline

GCP 上で、大規模プロダクトを想定した推薦システムを作る練習用のリポジトリです。

全体の流れは次のとおりです。

1. **Two-Tower** の学習を日次で行う
2. 毎時、ユーザーベクトルを推論し、**Vertex AI Vector Search** で近傍探索して、結果を **Bigtable** に保存する
3. **推薦 API** が Bigtable の候補を読み出す
4. **リアルタイム Reranker** がリクエストのたびに並べ替える

データは Kaggle の H&M Personalized Fashion Recommendations を使います。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/00_research_notes.md](docs/00_research_notes.md) | 国内外のテックブログの調査ノート（出典付き） |
| [docs/01_architecture.md](docs/01_architecture.md) | アーキテクチャ設計書 |
| [docs/02_roadmap.md](docs/02_roadmap.md) | 実装ロードマップ（Phase 0〜6） |

## はじめかた

```bash
cp .env.example .env   # PROJECT_ID / BILLING_ACCOUNT_ID を設定
make setup             # uv sync
make help              # コマンド一覧
```

各 Phase の解説は [docs/phases/](docs/phases/) にあります（[Phase 0](docs/phases/phase0.md)）。

## 周期

| コンポーネント | 周期 |
|---|---|
| Two-Tower 学習、item index の再構築 | 日次 |
| user 推論、近傍探索、Bigtable への書き込み | 毎時 |
| Reranker | リクエストごと（リアルタイム） |

> ⚠️ Bigtable、Vector Search の deploy、Dataflow streaming は、起動している間ずっと課金されます。
> 練習が終わったら必ず停止または削除してください（[コスト戦略](docs/01_architecture.md#12-コスト戦略)）。
