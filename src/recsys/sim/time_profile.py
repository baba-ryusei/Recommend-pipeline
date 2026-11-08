"""日内時刻の合成プロファイル。

H&M の取引は日付（t_dat）しか持たないので、「毎時アクティブなユーザー」が自然に入れ替わるよう
EC の典型的な時間帯分布で時刻を合成する。

- 同一顧客・同一日の購入は 1 セッションとみなし、セッション開始時刻を (customer_id, date) の
  ハッシュから決める → 1 人のユーザーが 1 日に何度も「別の時間帯に」現れることを防ぐ
- 各アイテムはセッション開始から 0〜ITEM_SPREAD_SEC 秒後に散らす

ハッシュ → 時（hour）の変換は BigQuery の RANGE_BUCKET で行う。境界値はこのモジュールで生成して
SQL テンプレートに埋め込む（SQL と Python で分布定義が二重管理にならないように）。
"""

from __future__ import annotations

from bisect import bisect_right
from itertools import accumulate

# 0 時〜23 時（JST）の相対的な重み（‰）。昼休みと 20〜22 時にピーク。合計 1000。
HOURLY_WEIGHTS_PERMILLE: tuple[int, ...] = (
    30, 18, 10, 6, 5, 6,      # 0-5
    12, 22, 30, 38, 44, 50,   # 6-11
    67, 52, 48, 46, 46, 48,   # 12-17
    54, 72, 80, 86, 80, 50,   # 18-23
)  # fmt: skip

BUCKET_RESOLUTION = 1000
ITEM_SPREAD_SEC = 20 * 60


def hour_boundaries() -> list[int]:
    """RANGE_BUCKET 用の境界（各時刻の累積上限。最後の 23 時分は不要なので 23 個）。"""
    cumulative = list(accumulate(HOURLY_WEIGHTS_PERMILLE))
    return cumulative[:-1]


def hour_for_bucket(bucket: int) -> int:
    """BigQuery の RANGE_BUCKET(bucket, hour_boundaries()) と同じ結果を返す（テスト用）。"""
    return bisect_right(hour_boundaries(), bucket)


def validate() -> None:
    if len(HOURLY_WEIGHTS_PERMILLE) != 24:
        raise ValueError("HOURLY_WEIGHTS_PERMILLE must have 24 entries")
    if sum(HOURLY_WEIGHTS_PERMILLE) != BUCKET_RESOLUTION:
        raise ValueError(f"weights must sum to {BUCKET_RESOLUTION}")


validate()
