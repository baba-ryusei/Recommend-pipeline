-- stg.sim_config: シミュレーション時刻の基準（1 行だけのテーブル）
--   time_offset_days : データセット日付 + offset = 実時刻（壁時計）の日付
--   replay_start_ts  : これより前が「履歴期間」（BQ に一括投入済み扱い）、以降が「リプレイ期間」
-- 基準日を付け替えたいときは `make stg REPLAY_START=YYYY-MM-DD` で stg ごと作り直す。
CREATE OR REPLACE TABLE `${project}.stg.sim_config`
OPTIONS (description = "simulation clock anchor (single row)")
AS
SELECT
  ${time_offset_days} AS time_offset_days,
  DATE '${replay_start_dataset_date}' AS replay_start_dataset_date,
  DATE '${replay_end_dataset_date}' AS replay_end_dataset_date,
  TIMESTAMP('${replay_start_wall_date}', '${timezone}') AS replay_start_ts,
  CURRENT_TIMESTAMP() AS anchored_at
