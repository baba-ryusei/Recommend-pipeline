"""環境設定。

リソース名は PROJECT_ID から機械的に決まる（Terraform 側の命名と一致させる）。
名前の組み立てをこのモジュールに集約し、各所で文字列を直書きしない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_REGION = "asia-northeast1"
DEFAULT_COMPETITION = "h-and-m-personalized-fashion-recommendations"

# データセット時刻を表すタイムゾーン（日内時刻の合成もこの TZ の「時」で行う）
SIM_TIMEZONE = "Asia/Tokyo"


@dataclass(frozen=True)
class Settings:
    project_id: str
    region: str = DEFAULT_REGION
    kaggle_competition: str = DEFAULT_COMPETITION

    @property
    def raw_bucket(self) -> str:
        return f"{self.project_id}-raw"

    @property
    def ml_bucket(self) -> str:
        return f"{self.project_id}-ml"

    @property
    def staging_bucket(self) -> str:
        return f"{self.project_id}-staging"

    def table(self, dataset: str, name: str) -> str:
        """BigQuery の完全修飾テーブル名 `project.dataset.table`。"""
        return f"{self.project_id}.{dataset}.{name}"


def get_settings(project_id: str | None = None, region: str | None = None) -> Settings:
    pid = project_id or os.environ.get("PROJECT_ID")
    if not pid:
        raise SystemExit(
            "PROJECT_ID が未設定です（.env を作成するか --project を指定してください）"
        )
    return Settings(
        project_id=pid,
        region=region or os.environ.get("REGION", DEFAULT_REGION),
        kaggle_competition=os.environ.get("KAGGLE_COMPETITION", DEFAULT_COMPETITION),
    )
