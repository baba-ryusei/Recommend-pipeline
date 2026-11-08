-- stg.articles: 型変換（*_no / *_code / *_id の数値列を INT64 に）
--   article_id / product_code は先頭 0 を保持するため STRING のまま
CREATE OR REPLACE TABLE `${project}.stg.articles`
CLUSTER BY article_id
OPTIONS (description = "H&M articles (typed)")
AS
SELECT
  article_id,
  product_code,
  prod_name,
  SAFE_CAST(product_type_no AS INT64) AS product_type_no,
  product_type_name,
  product_group_name,
  SAFE_CAST(graphical_appearance_no AS INT64) AS graphical_appearance_no,
  graphical_appearance_name,
  SAFE_CAST(colour_group_code AS INT64) AS colour_group_code,
  colour_group_name,
  SAFE_CAST(perceived_colour_value_id AS INT64) AS perceived_colour_value_id,
  perceived_colour_value_name,
  SAFE_CAST(perceived_colour_master_id AS INT64) AS perceived_colour_master_id,
  perceived_colour_master_name,
  SAFE_CAST(department_no AS INT64) AS department_no,
  department_name,
  index_code,
  index_name,
  SAFE_CAST(index_group_no AS INT64) AS index_group_no,
  index_group_name,
  SAFE_CAST(section_no AS INT64) AS section_no,
  section_name,
  SAFE_CAST(garment_group_no AS INT64) AS garment_group_no,
  garment_group_name,
  NULLIF(detail_desc, '') AS detail_desc
FROM `${project}.raw.articles`
