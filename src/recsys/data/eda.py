"""stg の基本統計を Markdown で出力する。

設計判断に直結する数字を確認するのが目的:
- アクティブユーザー数/時（→ 毎時 FindNeighbors の件数・Dataflow の規模）
- リピート購入率（→ 購入済み商品を Reranker で除外するべきか）
- 人気の集中度（→ logQ 補正・多様化の必要性）
- 結合カバレッジ（→ 特徴量の欠損）

使い方:
    uv run python -m recsys.data.eda --out docs/eda/hm_summary.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from google.cloud import bigquery

from recsys.config import SIM_TIMEZONE, Settings, get_settings


def queries(s: Settings) -> list[tuple[str, str, str]]:
    """(見出し, 何を見るか, SQL)。"""
    tx = f"`{s.table('stg', 'transactions')}`"
    cu = f"`{s.table('stg', 'customers')}`"
    ar = f"`{s.table('stg', 'articles')}`"
    cfg = f"`{s.table('stg', 'sim_config')}`"
    tz = SIM_TIMEZONE
    return [
        (
            "全体",
            "件数・期間",
            f"""
            SELECT COUNT(*) AS transactions,
                   COUNT(DISTINCT customer_id) AS customers,
                   COUNT(DISTINCT article_id) AS articles,
                   MIN(dataset_date) AS min_dataset_date, MAX(dataset_date) AS max_dataset_date,
                   MIN(event_ts) AS min_event_ts, MAX(event_ts) AS max_event_ts
            FROM {tx}""",
        ),
        (
            "マスタ件数と結合カバレッジ",
            "取引に出てくる ID がマスタに存在する割合（低いと特徴量が欠損する）",
            f"""
            SELECT (SELECT COUNT(*) FROM {cu}) AS customers_master,
                   (SELECT COUNT(*) FROM {ar}) AS articles_master,
                   ROUND(AVG(IF(a.article_id IS NULL, 0, 1)), 4) AS article_coverage,
                   ROUND(AVG(IF(c.customer_id IS NULL, 0, 1)), 4) AS customer_coverage
            FROM {tx} t
            LEFT JOIN {ar} a USING (article_id)
            LEFT JOIN {cu} c USING (customer_id)""",
        ),
        (
            "履歴期間 / リプレイ期間",
            "sim_config.replay_start_ts で分割したときの規模",
            f"""
            SELECT IF(t.event_ts < cfg.replay_start_ts, 'history', 'replay') AS period,
                   COUNT(*) AS transactions,
                   COUNT(DISTINCT customer_id) AS customers,
                   MIN(event_ts) AS min_event_ts, MAX(event_ts) AS max_event_ts
            FROM {tx} t CROSS JOIN {cfg} cfg
            GROUP BY period ORDER BY period""",
        ),
        (
            "リプレイ期間のアクティブユーザー数 / 時",
            "毎時パイプラインで user tower → FindNeighbors にかける人数の目安",
            f"""
            WITH h AS (
              SELECT TIMESTAMP_TRUNC(event_ts, HOUR) AS hour, COUNT(DISTINCT customer_id) AS users
              FROM {tx} t CROSS JOIN {cfg} cfg
              WHERE t.event_ts >= cfg.replay_start_ts
              GROUP BY hour
            )
            SELECT COUNT(*) AS hours, ROUND(AVG(users), 1) AS avg_users,
                   APPROX_QUANTILES(users, 100)[OFFSET(50)] AS p50,
                   APPROX_QUANTILES(users, 100)[OFFSET(95)] AS p95,
                   MAX(users) AS max_users
            FROM h""",
        ),
        (
            "合成した時間帯の分布（JST）",
            "time_profile の重みどおりになっているか",
            f"""
            SELECT EXTRACT(HOUR FROM event_ts AT TIME ZONE '{tz}') AS hour_jst,
                   ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 4) AS share
            FROM {tx} GROUP BY hour_jst ORDER BY hour_jst""",
        ),
        (
            "ユーザーあたり購入数の分位点",
            "ヘビーユーザーの偏り（→ ユーザーごとのサンプル数上限 [Y1]）",
            f"""
            WITH u AS (SELECT customer_id, COUNT(*) AS n FROM {tx} GROUP BY customer_id)
            SELECT APPROX_QUANTILES(n, 10) AS deciles, MAX(n) AS max_n FROM u""",
        ),
        (
            "リピート購入率",
            "以前の日にも買った (顧客, 商品) の購入の割合（高ければ購入済み除外は慎重に）",
            f"""
            WITH f AS (
              SELECT dataset_date,
                     MIN(dataset_date) OVER (PARTITION BY customer_id, article_id) AS first_date
              FROM {tx}
            )
            SELECT ROUND(COUNTIF(dataset_date > first_date) / COUNT(*), 4) AS repeat_rate FROM f""",
        ),
        (
            "人気の集中度（直近 28 日）",
            "上位 1% / 10% の商品が購入に占める割合（→ logQ 補正・多様化の必要性）",
            f"""
            WITH recent AS (
              SELECT article_id FROM {tx}
              WHERE dataset_date > (SELECT DATE_SUB(MAX(dataset_date), INTERVAL 28 DAY) FROM {tx})
            ),
            c AS (SELECT article_id, COUNT(*) AS n FROM recent GROUP BY article_id),
            r AS (SELECT n, PERCENT_RANK() OVER (ORDER BY n DESC) AS pr FROM c)
            SELECT COUNT(*) AS active_articles,
                   ROUND(SUM(IF(pr <= 0.01, n, 0)) / SUM(n), 4) AS top1pct_share,
                   ROUND(SUM(IF(pr <= 0.10, n, 0)) / SUM(n), 4) AS top10pct_share
            FROM r""",
        ),
        (
            "週次の取引数（直近 12 週）",
            "季節性・トレンド（学習期間の選び方の参考）",
            f"""
            SELECT DATE_TRUNC(dataset_date, WEEK(MONDAY)) AS week, COUNT(*) AS transactions,
                   COUNT(DISTINCT customer_id) AS customers
            FROM {tx}
            WHERE dataset_date > (SELECT DATE_SUB(MAX(dataset_date), INTERVAL 84 DAY) FROM {tx})
            GROUP BY week ORDER BY week""",
        ),
    ]


def to_markdown(rows: list[bigquery.Row]) -> str:
    if not rows:
        return "_(no rows)_"
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(row[h]) for h in headers) + " |")
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--project")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    settings = get_settings(project_id=args.project)
    bq = bigquery.Client(project=settings.project_id, location=settings.region)

    sections = ["# H&M EDA サマリ", "", "`uv run python -m recsys.data.eda` で生成。", ""]
    total_gb = 0.0
    for title, purpose, query in queries(settings):
        job = bq.query(query)
        rows = list(job.result())
        total_gb += (job.total_bytes_processed or 0) / 1e9
        sections += [f"## {title}", "", f"> {purpose}", "", to_markdown(rows), ""]
        print(f"  {title}: {len(rows)} rows")

    sections.append(f"_scanned {total_gb:.1f} GB in total_")
    report = "\n".join(sections)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
