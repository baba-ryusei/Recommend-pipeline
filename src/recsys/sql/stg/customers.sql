-- stg.customers: 型変換とカテゴリ値の正規化
--   fashion_news_frequency は原本で "NONE" / "None" が混在するので大文字に揃える
CREATE OR REPLACE TABLE `${project}.stg.customers`
CLUSTER BY customer_id
OPTIONS (description = "H&M customers (typed / normalized)")
AS
SELECT
  customer_id,
  COALESCE(SAFE_CAST(FN AS FLOAT64), 0) = 1 AS fn,
  COALESCE(SAFE_CAST(Active AS FLOAT64), 0) = 1 AS active,
  NULLIF(UPPER(TRIM(club_member_status)), '') AS club_member_status,
  CASE UPPER(TRIM(fashion_news_frequency))
    WHEN 'NONE' THEN 'NONE'
    WHEN 'REGULARLY' THEN 'REGULARLY'
    WHEN 'MONTHLY' THEN 'MONTHLY'
    ELSE NULL
  END AS fashion_news_frequency,
  SAFE_CAST(SAFE_CAST(age AS FLOAT64) AS INT64) AS age,
  NULLIF(postal_code, '') AS postal_code
FROM `${project}.raw.customers`
