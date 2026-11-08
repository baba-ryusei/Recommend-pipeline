"""BigQuery raw → stg（型変換・日内時刻の合成・時刻シフト）。

時間の扱い（docs/01_architecture.md §2）
- データセットの最後 `--replay-days` 日を「リプレイ期間」とし、その初日を壁時計の
  `--replay-start-wall`（既定: 今日 JST）に合わせるよう offset を決める
- 以降のパイプラインは shift 済みの event_ts だけを見ればよく、「今がデータセットのいつか」を意識しない

使い方:
    uv run python -m recsys.data.build_stg
    uv run python -m recsys.data.build_stg --replay-start-wall 2026-12-01 --replay-days 28
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from google.cloud import bigquery

from recsys import sql
from recsys.config import SIM_TIMEZONE, Settings, get_settings
from recsys.sim import time_profile

STG_TABLES = ("transactions", "customers", "articles")


@dataclass(frozen=True)
class SimAnchor:
    replay_start_dataset_date: date
    replay_end_dataset_date: date
    replay_start_wall_date: date

    @property
    def time_offset_days(self) -> int:
        return (self.replay_start_wall_date - self.replay_start_dataset_date).days


def compute_anchor(max_dataset_date: date, replay_days: int, replay_start_wall_date: date) -> SimAnchor:
    if replay_days < 1:
        raise ValueError("replay_days must be >= 1")
    start = max_dataset_date - timedelta(days=replay_days - 1)
    return SimAnchor(
        replay_start_dataset_date=start,
        replay_end_dataset_date=max_dataset_date,
        replay_start_wall_date=replay_start_wall_date,
    )


def render_statements(settings: Settings, anchor: SimAnchor) -> list[tuple[str, str]]:
    """(名前, SQL) のリスト。sim_config を最初に作る（transactions が参照するため）。"""
    common = {"project": settings.project_id, "timezone": SIM_TIMEZONE}
    statements = [
        (
            "sim_config",
            sql.render(
                "stg/sim_config.sql",
                **common,
                time_offset_days=anchor.time_offset_days,
                replay_start_dataset_date=anchor.replay_start_dataset_date.isoformat(),
                replay_end_dataset_date=anchor.replay_end_dataset_date.isoformat(),
                replay_start_wall_date=anchor.replay_start_wall_date.isoformat(),
            ),
        )
    ]
    for name in STG_TABLES:
        statements.append(
            (
                name,
                sql.render(
                    f"stg/{name}.sql",
                    **common,
                    bucket_resolution=time_profile.BUCKET_RESOLUTION,
                    hour_boundaries=time_profile.hour_boundaries(),
                    item_spread_sec=time_profile.ITEM_SPREAD_SEC,
                ),
            )
        )
    return statements


def fetch_max_dataset_date(bq: bigquery.Client, settings: Settings) -> date:
    query = f"SELECT MAX(SAFE_CAST(t_dat AS DATE)) AS d FROM `{settings.table('raw', 'transactions')}`"
    row = next(iter(bq.query(query).result()))
    if row.d is None:
        raise SystemExit("raw.transactions が空です。先に `make ingest` を実行してください")
    return row.d


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--project")
    parser.add_argument("--replay-days", type=int, default=28)
    parser.add_argument(
        "--replay-start-wall",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo(SIM_TIMEZONE)).date(),
        help="リプレイ期間の初日を壁時計のどの日に合わせるか（YYYY-MM-DD、既定: 今日）",
    )
    parser.add_argument("--dry-run", action="store_true", help="SQL を表示するだけで実行しない")
    args = parser.parse_args(argv)

    settings = get_settings(project_id=args.project)
    bq = bigquery.Client(project=settings.project_id, location=settings.region)

    max_date = fetch_max_dataset_date(bq, settings)
    anchor = compute_anchor(max_date, args.replay_days, args.replay_start_wall)
    print(
        f"dataset max date={max_date} / replay {anchor.replay_start_dataset_date}..{anchor.replay_end_dataset_date}"
        f" -> wall {anchor.replay_start_wall_date} (offset={anchor.time_offset_days} days)"
    )

    for name, statement in render_statements(settings, anchor):
        if args.dry_run:
            print(f"-- {name}\n{statement}\n")
            continue
        print(f"  build stg.{name} ...", end="", flush=True)
        job = bq.query(statement)
        job.result()
        gb = (job.total_bytes_processed or 0) / 1e9
        print(f" done ({gb:.2f} GB processed)")


if __name__ == "__main__":
    main()
