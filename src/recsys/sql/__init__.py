"""SQL テンプレート（パッケージデータとして同梱し、コンテナ内からも読めるようにする）。"""

from __future__ import annotations

from importlib.resources import files
from string import Template


def render(relative_path: str, **params: object) -> str:
    """`recsys/sql/<relative_path>` を読み込み `${name}` を置換する。未指定の変数があれば KeyError。"""
    text = files(__package__).joinpath(relative_path).read_text(encoding="utf-8")
    return Template(text).substitute({k: str(v) for k, v in params.items()})
