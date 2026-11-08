-- stg.transactions: 型変換 + 日内時刻の合成 + 時刻シフト
--
-- event_ts の作り方（recsys/sim/time_profile.py と対応）
--   1. 同一 (顧客, 日) を 1 セッションとみなし、セッション開始の「時」を時間帯分布に従って決める
--   2. 「分秒」もハッシュで決める
--   3. 各アイテムはセッション開始から 0〜${item_spread_sec} 秒後に散らす
--   4. データセット日付に sim_config.time_offset_days を足して実時刻へシフト
-- ハッシュは決定的なので、何度作り直しても同じ時刻になる（offset を変えた場合は日付だけずれる）。
--
-- MOD(MOD(x, n) + n, n) は負のハッシュ値でも 0..n-1 にするため（ABS は INT64 最小値で溢れる）。
CREATE OR REPLACE TABLE `${project}.stg.transactions`
PARTITION BY event_date
CLUSTER BY customer_id, article_id
OPTIONS (description = "H&M transactions with synthesized intraday time, shifted by stg.sim_config.time_offset_days")
AS
WITH
cfg AS (
  SELECT time_offset_days FROM `${project}.stg.sim_config`
),
typed AS (
  SELECT
    SAFE_CAST(t_dat AS DATE) AS dataset_date,
    customer_id,
    article_id,
    SAFE_CAST(price AS FLOAT64) AS price,
    SAFE_CAST(sales_channel_id AS INT64) AS sales_channel_id
  FROM `${project}.raw.transactions`
),
numbered AS (
  -- 同一 (顧客, 商品, 日) の重複行（同じ商品を複数個購入）を区別する連番
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY customer_id, article_id, dataset_date
      ORDER BY price, sales_channel_id
    ) AS dup_seq
  FROM typed
),
timed AS (
  SELECT
    *,
    RANGE_BUCKET(
      MOD(MOD(FARM_FINGERPRINT(CONCAT('h|', customer_id, '|', CAST(dataset_date AS STRING))), ${bucket_resolution}) + ${bucket_resolution}, ${bucket_resolution}),
      ${hour_boundaries}
    ) AS session_hour,
    MOD(MOD(FARM_FINGERPRINT(CONCAT('s|', customer_id, '|', CAST(dataset_date AS STRING))), 3600) + 3600, 3600) AS session_sec,
    MOD(
      MOD(FARM_FINGERPRINT(CONCAT('i|', customer_id, '|', article_id, '|', CAST(dataset_date AS STRING), '|', CAST(dup_seq AS STRING))), ${item_spread_sec})
      + ${item_spread_sec},
      ${item_spread_sec}
    ) AS item_offset_sec
  FROM numbered
),
shifted AS (
  SELECT
    timed.*,
    TIMESTAMP_ADD(
      TIMESTAMP(DATE_ADD(dataset_date, INTERVAL cfg.time_offset_days DAY), '${timezone}'),
      INTERVAL (session_hour * 3600 + session_sec + item_offset_sec) SECOND
    ) AS event_ts
  FROM timed
  CROSS JOIN cfg
)
SELECT
  -- 決定的な取引 ID（後でイベントとして流すときの event_id / 重複排除キーになる）
  TO_HEX(MD5(CONCAT(customer_id, '|', article_id, '|', CAST(dataset_date AS STRING), '|', CAST(dup_seq AS STRING)))) AS txn_id,
  customer_id,
  article_id,
  price,
  sales_channel_id,
  dataset_date,
  event_ts,
  DATE(event_ts, '${timezone}') AS event_date
FROM shifted
WHERE dataset_date IS NOT NULL
