# テックブログ調査ノート

- 調査日: 2026-11-08
- 出典は、調査時に本文を確認できたものだけを載せています。開けずに二次情報で補ったものには「※」を付けています。
- 価格は us-central1 のオンデマンド価格です（2026-11-08 時点）。東京リージョンの価格は確認できていないので、構築前に Pricing Calculator で確認してください。

---

## TL;DR: 設計に持ち込む 12 のこと

| # | 学び | 主な出典 |
|---|---|---|
| 1 | 目標構成（日次学習＋毎時ユーザー推論＋Vector Search＋Bigtable）は ZOZOTOWN ホームが本番で効果を出している構成とほぼ同じ | [Z1] |
| 2 | **最重要はモデルのバージョン整合**。user tower と item index は必ず同じ版を使う。index のデプロイが終わってから active を切り替え、毎時ジョブは active を読む | [Z1][Z2][Y2][P1] |
| 3 | index は**版ごとに新しく作る（blue/green）**。同じ index を全件上書きすると反映が非同期なので、新旧の空間が混ざる | [G3][Y2][Z3] |
| 4 | 毎時の推論は**直近アクティブなユーザーだけ**の差分にする。Vector Search の更新件数を絞るとコストが大きく下がる | [Z2][Z7] |
| 5 | 学習は in-batch softmax＋**logQ 補正**＋L2 正規化＋temperature が定番 | [Y2][U1][S1][T1] |
| 6 | 評価は「モデルの recall@K（翌日 holdout）」と「ANN の recall（厳密検索との比較）」を**分けて測り**、両方をゲートにする | [G1][F1][E1] |
| 7 | Bigtable の候補行には `model_version` と `generated_at` を必ず持たせる | [Z1][Z3] |
| 8 | 「代わり映えしない」対策は、学習不要の後処理（既出ペナルティ＋確率的な揺らぎ＋多様化＋探索枠）から始める | [Z4][RR1][RR3][RR4] |
| 9 | **初日から** request_id / model_version / position / propensity 付きのインプレッションログを取る。後で ML reranker を作るときやオフ方策評価（OPE）に必要になる | [Z5][F1] |
| 10 | キャッシュはインメモリ＋Redis 系＋singleflight が定番。ただし**リランク結果をユーザー横断でキャッシュするとパーソナライズが壊れる**。ヒット率を計測してから層を足す | [C1][C2] |
| 11 | フォールバック（人気順リスト）は GCS に出力し、API のメモリに保持する | [C2] |
| 12 | embedding の品質監視（NULL・ゼロベクトル率、鮮度、スコア分布の PSI）を日次で回す | [Z6] |

---

## 1. 参照した事例

### 1.1 国内

| ID | 会社 | タイトル / URL | 要点 |
|---|---|---|---|
| Z1 | ZOZO | [商品クリック58%増・経由受注26%増の裏側 - Two-Tower×Vertex AI Vector Search](https://techblog.zozo.com/entry/home-module-contents-personalization) (2025-06) | 日次の Pipelines で両タワーを学習し、約100万商品の index を更新する。毎時ジョブで user tower → ANN（crowding で同一ブランド3件まで）→ 直近閲覧品の減点 → Bigtable に保存。**index の更新が終わってから Model Registry のエイリアスを付け替え、毎時ジョブはそのエイリアスを読む** |
| Z2 | ZOZO | [Embedding基盤の構築と運用](https://techblog.zozo.com/entry/embedding-pf) (2025-11) | User/Item Tower をペアで Manifest テーブルに登録し、STAGING/ACTIVE/ARCHIVE で管理する（ACTIVE は常に1つ）。商品は日次の全件更新、ユーザーは毎時の差分更新。学習後に空間を揃える方式（アンカーで線形変換）は保守が重いので採用しなかった。バッチは BigQuery VECTOR_SEARCH、オンラインは Vertex AI Vector Search |
| Z3 | ZOZO | [embeddingベースの推薦でA/Bを高速に回す配信基盤REP](https://techblog.zozo.com/entry/rep-embedding-platform) (2026-09) | 新版を先に書き込み、そのあと有効化と旧版の無効化を1トランザクションで行う。A/B は `hash(user_id, test_name)` で決定的に振り分け、テストの設定は YAML を PR → CI で管理する |
| Z4 | ZOZO | [ホーム画面パーソナライズ最新アップデート](https://techblog.zozo.com/entry/module-personalize-phase2) (2025-02) | 学習目的をクリックからカート投入に変えた。「見たのにクリックしなかった」ものを下げる（＝疲労ペナルティ）。中期の嗜好は安定する代わりに反応が遅い |
| Z5 | ZOZO | [バンディットを用いた推薦システムの構成](https://techblog.zozo.com/entry/zozoresearch-bandit-overviews) (2020-11) | 返却するアイテムごとに配信 ID を振り、データ版・予測 CTR・コンテキストと一緒に記録する。imp/click/CV は Pub/Sub → Dataflow → BigQuery。**処理時刻ではなくイベント時刻で処理する**。遅れて届く CV はストリーミング学習から外す |
| Z6 | ZOZO | [複数サービスに配信するembeddingの品質監視](https://techblog.zozo.com/entry/embedding-quality-monitoring) (2026-10) | NULL・ゼロベクトル率が 0.1% を超えたら、最終書き込みから 12 時間を超えたら、スコア分布の PSI が 0.5 を超えたら警告する（PSI の一般的な閾値 0.2 はノイズが多すぎた）。BigQuery のスケジュールクエリで `ERROR()` を起こして通知する |
| Z7 | ZOZO | [WEARへのVertex AI Vector Search導入と実践](https://techblog.zozo.com/entry/introduction-and-practice-of-vertex-ai-vector-search) (2025-08) | TreeAH・1,400万件・256次元・日次の BATCH_UPDATE で、p99 は 60〜120ms。**落とし穴**: leafNodeEmbeddingCount=100 だとクエリが数秒かかった（15,000 にすると数十 ms）／upsert と delete を同じ呼び出しで送ると delete が黙って失敗する／更新件数を絞るとコストが 80% 以上下がった |
| Z8 | ZOZO | [「おすすめアイテム」を支える推薦システム基盤](https://techblog.zozo.com/entry/zozotown-item-recommend-infra-arch) (2020-11) | Bigtable＋Redis のキャッシュ。Bigtable の RPC タイムアウトを短くしてリトライを増やすと p99 が約 29% 改善した。Pub/Sub は重複配信がありうるので、ジョブを冪等にする |
| M1 | Mercari | [CF + Vector Search で類似商品推薦を改善](https://engineering.mercari.com/en/blog/entry/20230612-cf-similar-item) (2023-06) | 全ベクトルは Bigtable に置き、ANN には販売中の商品だけを入れる。最初の A/B は失敗した（長く売れ残った商品ばかり推薦していた）。**オフライン評価が鮮度の問題を隠していた** |
| M2 | Mercari (GC Blog) | [Mercari leverages Google's vector search](https://cloud.google.com/blog/topics/developers-practitioners/mercari-leverages-googles-vector-search-technology-create-new-marketplace) (2022-06) | Pipelines で BigQuery の差分を取ってベクトル化し、Matching Engine と Bigtable の両方に書く。Cloud Run で配信する |
| M3 | Mercari | [Item2vecで推薦精度改善](https://engineering.mercari.com/en/blog/entry/20221004-attempt-to-improve-item-recommendation-accuracy-using-item2vec/) (2022-10) | 学習は月次。BigQuery でユーザーごとの推薦を毎時生成して Bigtable に保存し、ホーム表示時に参照する |
| M4 | Mercari | [The Journey to Machine-Learned Re-ranking](https://engineering.mercari.com/en/blog/entry/20230101-the-journey-to-machine-learned-re-ranking/) (2023-01) | 1段目で取りこぼしたものはリランクでは救えない。ラベルは段階的にする（click < 購入）。bot は除外する。position bias の補正は未対応 |
| L1 | LINEヤフー | [ヤフートップページ 記事推薦の試行錯誤](https://techblog.lycorp.co.jp/ja/20260202a) | ユーザーベクトルは1日数回のバッチで KVS に入れる。多様化として cos>0.98 の重複除去とクラスタ単位の上限を使う。KL ペナルティでのリランクは計算が重く検討中。複数シードで学習して最良を採用する |
| L2 | LINEヤフー | [Milvus: LINE VOOM リアルタイムレコメンド](https://techblog.lycorp.co.jp/ja/20251028a) | 日次の候補プールでは新規投稿の反映が最大1日遅れていた。オンライン ANN にしたら、当日に露出する投稿が 39 倍以上になった。二重書き込み＋alias 切替で可用性を確保 |
| L3 | LINEヤフー | [Embedding安定化で Cold start を解決（LINEバイト）](https://techblog.lycorp.co.jp/ja/techverse2026-62) | 日次で再学習した two-tower の embedding は、日をまたぐと相関がほぼ0になる。そのまま reranker の特徴量にすると nDCG が悪化した。直交 Procrustes で前日の空間に揃えると改善した |
| C1 | CyberAgent | [ABEMAの推薦システムにおけるアーキテクチャの歴史](https://developers.cyberagent.co.jp/blog/archives/48661/) (2024-07) | 構成は BFF → Gateway（候補・特徴量を取得）→ Reranker。キャッシュキーの設計を誤ってパーソナライズが崩れた |
| C2 | CyberAgent | [ABEMA レコメンドのアーキテクチャ変遷 CADC2024](https://developers.cyberagent.co.jp/blog/archives/51276/) (2024-11) | Gateway が Bigtable を直接読む。リランクのキャッシュをやめて p99 が約 50% 改善。ヒット率を計測したうえで Memorystore を廃止した。フォールバックは GCS に出力してメモリに保持する |
| C3 | CyberAgent | [Contextual Bandit レコメンド構築 バックエンド編](https://developers.cyberagent.co.jp/blog/archives/57070/) (2025-06) | Pipelines が毎時パラメータを BigQuery に書き、Pub/Sub で Worker に通知して Redis に載せる。2段キャッシュ＋singleflight |
| R1 | リクルート | [Two-Towerモデルと近似最近傍探索による候補生成](https://blog.recruit.co.jp/data/articles/two-tower-model/) (2023-09) | in-batch の対照学習。数値特徴は log1p 変換が最良だった。ScaNN で検索は 1ms 未満。日次バッチ |
| T1 | タイミー | [In-Batch Negative Samplingの課題と対策](https://tech.timee.co.jp/entry/2025/12/21/090000) (2025-12) | 人気バイアスには logQ 補正。偽負例（同じアイテムが別の行の負例になる）はマスクで除く |
| PX | pixiv | [inside.pixiv.blog の記事（作品詳細レコメンドの多様化事例）](https://inside.pixiv.blog/mytk/7942) | 多様化（Ziegler 2005 の TDA）を作品推薦に適用し、ユニーククリックが約 +10% |

### 1.2 海外

| ID | 会社 | タイトル / URL | 要点 |
|---|---|---|---|
| G1 | Google Cloud | [Implement two-tower retrieval for large-scale candidate generation](https://docs.cloud.google.com/architecture/implement-two-tower-retrieval-large-scale-candidate-generation) | 2つのタワーを分けて Registry に登録する。candidate tower は batch prediction で GCS（JSON）に出し、それで index を作る。**brute-force の index を別に作って ANN の recall を比較する** |
| G2 | Google Cloud | [Scaling deep retrieval with TFRS and Vertex AI Matching Engine](https://cloud.google.com/blog/products/ai-machine-learning/scaling-deep-retrieval-tensorflow-two-towers-architecture) (2023-04) / [repo](https://github.com/jswortz/spotify_mpd_two_tower) | BigQuery → Dataflow → GCS → Training → Pipelines。未来の情報を学習データから外す（リーク防止）。hashing のビン数はユニーク値の数より多くする |
| G3 | Google Cloud | [Update and rebuild an active index](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/update-rebuild-index) / [Deploy index](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/deploy-index-public) | batch と streaming は作成後に変えられない。デプロイに 20〜30 分、undeploy に最大 30 分かかる。1エンドポイントあたり index は 20 個まで。マシンタイプは後から変えられない |
| Y1 | YouTube | [Deep Neural Networks for YouTube Recommendations](https://research.google/pubs/pub45530) (2016) | 推薦経由に限らず全視聴から学習する。ユーザーごとのサンプル数に上限を設ける。未来の情報は入力から外す。オフライン指標と A/B の結果は一致しないことがある |
| Y2 | YouTube | [Sampling-Bias-Corrected Neural Modeling](https://research.google/pubs/sampling-bias-corrected-neural-modeling-for-large-corpus-item-recommendations/) (2019) | in-batch softmax＋logQ 補正（頻度はストリーミングで推定）。L2 正規化＋temperature。**query tower と index を1つの SavedModel に結合し、版を原子的に揃える**。評価は日ごとの holdout の 7 日平均 |
| F1 | Meta | [Embedding-based Retrieval in Facebook Search](https://arxiv.org/pdf/2006.11632v2.pdf) (KDD 2020) | 負例を「表示されたがクリックされなかった」ものだけにすると recall が大きく下がった。hard negative は少量を easy negative と混ぜる。検索時にモデル ID を明示する。モデルを変えたら ANN パラメータを再調整する |
| F2 | Meta | [Scaling the Instagram Explore recommendations system](https://engineering.fb.com/2023/08/09/ml-applications/scaling-instagram-explore-recommendations-system/) (2023-08) | 候補ソースは複数あり、重み付きで混ぜる。item は日次で ANN に入れ、user はリクエスト時に計算する。2段目の上位を教師にして two-tower を蒸留する |
| P1 | Pinterest | [Establishing a Large Scale Learned Retrieval System](https://medium.com/pinterest-engineering/establishing-a-large-scale-learned-retrieval-system-at-pinterest-eb0eaf7b92c5) (2024) ※原文は 403 で開けず、要約で確認 | ANN ホストに「モデル名 → 版」のメタデータを index と一緒に持たせ、バックエンドはその版の user tower を使う。ロールバック用に user tower の直近 N 版を保持する |
| U1 | Uber | [Two Tower Embeddings at Uber](https://www.uber.com/en-JP/blog/innovative-recommendation-applications-using-two-tower-embeddings/) | logQ 補正で recall@500 が 89% → 93%。バッチ内で意味のある負例になるよう、データの並べ方を工夫する |
| S1 | Snap | [Embedding-based Retrieval with Two-Tower Models in Spotlight](https://eng.snap.com/embedding-based-retrieval) (2023-06) | user embedding はオフラインで数時間おきに更新する。HNSW の index は GCS に置く。feed と retrieval のサービスを分ける |
| A1 | Airbnb | [Embedding-Based Retrieval for Airbnb Search](https://airbnb.tech/ai-ml/embedding-based-retrieval-for-airbnb-search/) | 負例の最適解はドメインによって変わる（Facebook と逆の結論）。更新が多くフィルタも使うので、HNSW ではなく IVF を採用した |
| E1 | Etsy | [Unified Embedding Based Personalized Retrieval](https://arxiv.org/html/2306.04833v2) (2023) | 評価は翌日以降の購入に対する Recall@100/1000。K が大きいと HNSW の recall が落ちる。キャッシュキーにセッション ID を入れるとヒット率が下がる |
| LI1 | LinkedIn | [LiNR: Model Based Neural Retrieval on GPUs](https://arxiv.org/html/2407.13218v3) (2024) | 定期的に作り直すのではなく、live で upsert する（+6%）。post-filter は recall を下げるので、pre-filter を使う |

### 1.3 リランキング（停滞・多様性・探索）

| ID | 出典 | 要点 |
|---|---|---|
| RR1 | LinkedIn, Impression Discounting (KDD'14) [slides](https://slideshare.net/mitultiwari/impression-kdd) | 表示回数・最後に見た時刻・表示位置などからペナルティを作る |
| RR2 | Bing News, User Fatigue (WWW'16) [link](https://researchwith.stevens.edu/en/publications/user-fatigue-in-online-news-recommendation/) | 既出アイテムへの過去の反応に応じて、下げるか上げるかを切り替える。最大 +15% |
| RR3 | Chen+ Fast Greedy MAP for DPP (NeurIPS'18) [link](https://ar5iv.arxiv.org/html/1709.05135) | DPP の貪欲法を O(K²N) で計算でき、p99 は数 ms。A/B で MMR を上回った |
| RR4 | YouTube, Practical Diversified Recommendations with DPP (CIKM'18) [link](https://dblp.uni-trier.de/rec/conf/cikm/WilhelmRBJCG18.html) | YouTube ホームで短期・長期のエンゲージメントが向上した |
| RR5 | Xiaohongshu, Sliding Spectrum Decomposition (KDD'21) [link](https://ar5iv.arxiv.org/html/2107.05204) | 無限スクロール向けの多様化。N×N の行列を作らずに済む |
| RR6 | Steck, Calibrated Recommendations (RecSys'18) ※著者以外が置いた PDF | 履歴のカテゴリ分布に推薦リストを近づける（KL を使う） |
| RR7 | Carbonell & Goldstein, MMR (SIGIR'98) [link](https://people.eng.unimelb.edu.au/ammoffat/sigir98/abstracts/carbonell.html) | 最も簡単な多様化手法 |
| RR8 | Li+ LinUCB (WWW'10) [link](https://arxiv.org/abs/1003.0146) | Contextual bandit。Yahoo! ニュースで +12.5% |
| RR9 | Eugene Yan, Bandits for recommender systems [link](https://eugeneyan.com/writing/bandits/) | Spotify・Netflix・DoorDash などのバンディット事例集 |
| RR10 | Open Bandit Dataset / Pipeline (ZOZO) [link](https://arxiv.org/abs/2008.07146v4) | オフ方策評価（IPS/DR）の実装と、そのためのデータ |
| RR11 | Basu+ LinkedIn, Constrained Multi-objective Optimization [link](https://ar5iv.labs.arxiv.org/html/1602.04391) | 双対問題をオフラインで解き、オンラインではユーザーごとに小さな問題を解く |
| RR12 | Gumbel top-k / Plackett-Luce sampling [link](https://arxiv.org/abs/2205.06024v1) | スコアに Gumbel ノイズを足してから並べるとサンプリングになる。傾向スコアも計算できる |
| RR13 | Ziegler+ Topic Diversification (WWW'05) [link](https://archives.iw3c2.org/www2005/proceedings/docs/p22.pdf) | ILS（リスト内の類似度）の定義と多様化 |

---

## 2. テーマ別の学び

### 2.1 周期の設計
- 「学習は日次、item index も日次、user は毎時」は ZOZO が本番で実証済み [Z1]。毎時の対象は**直近のアクティブユーザーだけ**にする [Z2]。
- item 側の更新は多くの社で日次〜数時間おき [Y2][F2][S1]。鮮度が必要なら、新しいアイテムだけ差分で追加する（`contentsDeltaUri`）か、streaming index を使う [G3][L2][LI1]。
- 日次バッチの候補だけでは新しいアイテムの反映が遅れる [L2][LI1]。今回は対象外にするが、オンラインで user tower を推論する経路は発展課題として残す。

### 2.2 モデルのバージョン整合（最重要）
- **起きること**: 日次で再学習すると埋め込み空間は毎回まったく変わる（日をまたいだ相関がほぼ0 [L3]）。v2 の user ベクトルで v1 の index を引くと、ほぼランダムな候補が返る [P1]。
- **各社の対策**:
  - ZOZO: index の更新が終わってからエイリアスを付け替え、毎時ジョブはエイリアスを読む [Z1]。Manifest で ACTIVE を1つに保ち、切替は1トランザクションで行う [Z2][Z3]
  - YouTube: query tower と index を1つのモデルに結合する [Y2]
  - Pinterest: index 側に版のメタデータを持たせる [P1]
  - Facebook: クエリにモデル ID を明示する [F1]
- **見落としやすい点**: reranker の特徴量に embedding を使う場合も、学習時と配信時で版を揃える必要がある [L3]。

### 2.3 学習（負例・損失）
- in-batch softmax＋logQ 補正（サンプリング確率を補正して人気バイアスを抑える）＋L2 正規化＋temperature [Y2][U1][S1][T1]。
- 同じアイテムが別の行の負例として入る「偽負例」はマスクで除く [T1]。hard negative は少量だけ混ぜる [F1]。
- 学習データは**推薦経由に限らない行動**から作る。未来の情報が入らないようにし（point-in-time）、ユーザーごとのサンプル数に上限を設ける [Y1][G2]。
- 前処理（hash など）はモデル側か共通コードに置き、学習と推論で同じものを使う [G2]。

### 2.4 ANN / Vector Search の運用
- leafNodeEmbeddingCount を小さくしすぎない。upsert と delete は別々の呼び出しで送る。リージョンを揃える [Z7]。
- ANN の recall を brute-force との比較で継続的に測り、モデルを変えたら再調整する [G1][F1][E1]。
- 除外したいアイテムは restricts で事前に絞る（pre-filter）[LI1][G2]。ただし Vector Search には**ID 単位で除外するリストがない**ので、購入済み品の除外は reranker 側で行う（§3）。
- 同じブランドが並びすぎないよう、crowding（同一グループの上限）を使う [Z1]。

### 2.5 サービング
- 事前に計算した候補は Bigtable に置く。ZOZO・メルカリ・ABEMA に共通する解 [Z1][M3][C2]。
- 構成は Gateway（候補と特徴量を集める）→ Reranker（計算だけ）に分ける [C1][C2]。
- Bigtable クライアントはタイムアウトを短くし、リトライを増やす [Z8]。
- キャッシュのキーに model_version を入れる。セッション内で変わる特徴はキーに入れない [E1]。

### 2.6 リランキング（停滞対策）
- 停滞の原因は2つある。リランクが決定論的なこと（同じ入力なら同じ並び）と、スコアに「既に見せたか」が入っていないこと。
- 実例:
  - 既出・未クリックの減点 [Z1][Z4][RR1][RR2]
  - 重複除去とクラスタ上限 [L1]
  - DPP [RR3][RR4]
  - Thompson Sampling による探索 [Z5][C3]
- 多様化を効かせすぎると CTR が落ちる（ある事例では DPP サンプリングで −37〜46%）。一方、外すと長期で効いてくる（Pinterest では DPP を外すと初日は上がったが、1週間後に −2%）。パラメータは小さい値から始め、A/B は 2週間以上回す。
- 詳細の設計は [01_architecture.md §9](./01_architecture.md#9-reranker-設計) を参照。

### 2.7 ログ・評価・監視
- 返却したリストごとに、request_id、model_version、policy_version、seed、retrieval スコア・順位、最終順位、explore フラグ、傾向スコアを記録する [Z5][F1]。
- 表示とクリックはイベント時刻で処理し、重複を除き、冪等にする [Z5][Z8]。
- embedding の品質監視として、NULL・ゼロベクトル率、鮮度、PSI を見る [Z6]。
- A/B は `hash(user_id, experiment)` で振り分け、設定は YAML＋CI で管理する [Z3]。

---

## 3. GCP の最新仕様メモ（2026-11 時点）

調査エージェントが公式ドキュメントで確認した内容です。

- **名称変更**: 2026-04 から、Vertex AI の多くのドキュメントが「Gemini Enterprise Agent Platform」名義になり、パスも移っている（[release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes)）。このリポジトリでは従来どおり「Vertex AI」と書く。
- **Vector Search には2系統ある**:
  - 1.0（Index / IndexEndpoint）: デプロイしたノードの時間で課金される。最小は e2-standard-2 で **$0.0938/node-hr**。Small シャード（2GiB）まで。index のビルドとバッチ更新は $3/GiB。
  - 2.0（Collection 型、現在の名称は Agent Retrieval）: 2026-03 に GA。VM の管理が不要で、**読み取り操作数で課金される**（[pricing](https://cloud.google.com/products/gemini-enterprise-agent-platform/pricing)）。
  - → **毎時、多数のユーザーをまとめて検索する今回の用途では 1.0 が固定費で済む**。2.0 では、検索1回あたり「index 内 100 件ごとに 1 op」課金という試算になり、割高になる。
- **フィルタ**: token / numeric restricts が使える。datapoint ID で除外するリストはない（[filtering](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/filtering)）。
- **クエリ**: FindNeighbors は1リクエストに複数のクエリを入れられる。neighbor_count は 300 以下が推奨（[query](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/query-index-public-endpoint)）。
- **Bigtable**:
  - 最小 1 ノード（Enterprise $0.65/node-hr ≒ **$475/月**）。アイドル中も課金される（[pricing](https://cloud.google.com/bigtable/pricing)）。
  - 無料トライアルインスタンスがある。1 ノード・500GB・1 プロジェクト1回まで（[free trial](https://docs.cloud.google.com/bigtable/docs/free-trial-instance)）。
  - GC は遅延して実行されるので、**期限切れのセルも読めてしまう**。読むときにタイムスタンプでフィルタする（[GC](https://docs.cloud.google.com/bigtable/docs/garbage-collection)）。
  - aggregate 型のカラムファミリー（`AddToCell` で sum などを加算する）がある（[aggregates](https://cloud.google.com/bigtable/docs/aggregates)）。
  - 行キーにタイムスタンプや連番を先頭で置かない（[schema design](https://docs.cloud.google.com/bigtable/docs/schema-design)）。
- **Pipelines**:
  - 確認時点のバージョン: kfp 2.18.0、google-cloud-pipeline-components 2.22.0、google-cloud-aiplatform 2.7.0（2.x 系で名前空間が再編されている）。
  - スケジュールは組み込みの Scheduler API で設定できる（`PipelineJobSchedule`、cron に `TZ=Asia/Tokyo` を指定可）。Cloud Scheduler は不要（[schedule](https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/pipelines/schedule-pipeline-run)）。
  - 実行1回 $0.03＋計算資源。
- **Model Registry**: エイリアスは 1 つの版にしか付けられない（[alias](https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/model-registry/model-alias)）。
- **Dataflow**:
  - streaming ワーカーの既定は 4 vCPU / 15GB。machine_type と max_num_workers を必ず明示する（[pricing](https://cloud.google.com/dataflow/pricing)）。
  - RunInference は PyTorch / TF / sklearn / ONNX に対応。
- **Pub/Sub**:
  - BigQuery サブスクリプションを使えば、Dataflow なしで生ログを BQ に書ける（[docs](https://docs.cloud.google.com/pubsub/docs/bigquery)）。
  - Bigtable サブスクリプションは Preview で、行キーが固定されるので、集計カウンタには使えない。
- **Memorystore for Valkey**: shared-core-nano（1.4GB）が $0.0318/hr ≒ $23/月。Cloud Run からつなぐには Direct VPC egress が必要（[pricing](https://cloud.google.com/memorystore/valkey/pricing)）。
- **Feature Store**: Optimized online serving は **2027-02-17 に終了**する（[docs](https://docs.cloud.google.com/vertex-ai/docs/featurestore/latest/online-serving-types)）。今回は Feature Store を使わず、Bigtable を自分で設計する。
- **BigQuery VECTOR_SEARCH**: 課金はスキャンしたバイト数（[docs](https://docs.cloud.google.com/bigquery/docs/vector-search-intro)）。今回は **ANN の recall を測るときの brute-force 正解データ**として使う。

### 常時起動した場合の月額（最小構成、us-central1）

| 項目 | 月額 |
|---|---|
| Bigtable 1 ノード | 約 $475 |
| Vector Search e2-standard-2 ×1 | 約 $68（blue/green で 2 つ同時に載せると ×2） |
| Dataflow streaming（2vCPU×1） | 約 $130〜180 |
| Valkey nano | 約 $23 |
| Cloud Run（2 サービス、min=1） | 約 $20 |
| 毎時バッチ・学習・Pipelines | 約 $15〜25 |
| **合計** | **約 $750〜830** |

→ **常時起動はしない**。練習する日だけ立ち上げる運用にする（[01_architecture.md §12](./01_architecture.md#12-コスト戦略)）。

---

## 4. データセット比較

| データセット | ユーザー特徴 | アイテム特徴 | 時刻 | 規模 | 評価 |
|---|---|---|---|---|---|
| **H&M Personalized Fashion Recommendations** (Kaggle) | 年齢、会員ステータス、ニュース購読頻度 | 商品タイプ・色・部門など多数＋説明文＋画像 | **日付のみ**（t_dat） | 取引 約3,180万、顧客 約137万、商品 約10.5万（※取得後に確認） | **採用**。two-tower の両タワーに特徴量を入れられる |
| MovieLens 32M | なし | ジャンル・タグ | 秒単位 | 3,200万評価 / 20万ユーザー | ユーザー特徴がない。代替案 |
| OTTO (Kaggle) | なし | なし（ID は匿名化） | ミリ秒単位 | 2.2億イベント | セッション型。特徴量がない |
| RetailRocket | なし | ハッシュ化された属性 | 秒単位 | 約276万イベント（※未検証） | 規模が小さい |

H&M の注意点:
- Kaggle のコンペ規約に同意しないとダウンロードできない。
- 時刻が日付単位なので、**毎時の挙動を再現するには時刻を合成する必要がある**（[01_architecture.md §2](./01_architecture.md#2-時間の扱い論理時刻とリプレイ)）。
- データは購入ログだけで、インプレッションとクリックが含まれない。これらはシミュレータで作る。
