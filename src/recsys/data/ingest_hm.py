"""Kaggle H&M → GCS raw → BigQuery raw。

設計方針
- GCS raw は「原本の不変コピー」。パスにデータ版（v1）を入れ、上書きしない
- BigQuery raw は **全列 STRING** でロードする。型変換は stg で行う
  （CSV の型推定に頼ると article_id 先頭の 0 が落ちる・空文字の扱いがぶれる等の事故が起きるため）
- 各ステップはスキップ可能かつ冪等（再実行しても同じ結果）

使い方:
    uv run python -m recsys.data.ingest_hm                 # 全部
    uv run python -m recsys.data.ingest_hm --skip-download # GCS にある前提で BQ ロードだけ
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from google.cloud import bigquery, storage
from google.cloud.storage import transfer_manager

from recsys.config import Settings, get_settings

DATA_VERSION = "v1"


@dataclass(frozen=True)
class SourceFile:
    file_name: str
    table: str


# 画像（約 30GB）は Phase 0 では取り込まない（後で画像特徴を使うときに別途）
SOURCES: tuple[SourceFile, ...] = (
    SourceFile("articles.csv", "articles"),
    SourceFile("customers.csv", "customers"),
    SourceFile("transactions_train.csv", "transactions"),
)

_INVALID_COLUMN_CHARS = re.compile(r"[^A-Za-z0-9_]")


def sanitize_column(name: str) -> str:
    """CSV ヘッダを BigQuery の列名として使える形にする。"""
    col = _INVALID_COLUMN_CHARS.sub("_", name.strip())
    if not col:
        raise ValueError("empty column name")
    if col[0].isdigit():
        col = f"_{col}"
    return col


def parse_header(head: bytes) -> list[str]:
    """ファイル先頭のバイト列から CSV ヘッダ行をパースする。"""
    text = head.decode("utf-8-sig", errors="strict")
    first_line = text.splitlines()[0]
    row = next(csv.reader(io.StringIO(first_line)))
    return [sanitize_column(c) for c in row]


# ---------------------------------------------------------------- download
def download(competition: str, src: SourceFile, dest_dir: Path) -> Path:
    """Kaggle CLI で 1 ファイルを取得する。zip で届いた場合は該当メンバーだけを取り出す。"""
    target = dest_dir / src.file_name
    if target.exists():
        print(f"  [skip] {target} exists")
        return target

    if shutil.which("kaggle") is None:
        raise SystemExit("kaggle CLI が見つかりません。`uv sync` 後に `uv run` 経由で実行してください")

    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "competitions", "download", competition, "-f", src.file_name, "-p", str(dest_dir)]
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    zip_path = dest_dir / f"{src.file_name}.zip"
    if zip_path.exists():
        _extract_single_member(zip_path, src.file_name, target)
        zip_path.unlink()

    if not target.exists():
        raise SystemExit(f"ダウンロード結果が見つかりません: {target}（コンペ規約に同意済みか確認）")
    return target


def _extract_single_member(zip_path: Path, member: str, target: Path) -> None:
    """zip から期待するメンバーだけを、こちらが決めたパスへ書き出す（パストラバーサル対策）。"""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if member not in names:
            raise SystemExit(f"{zip_path} に {member} がありません: {names[:5]}")
        with zf.open(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)


# ---------------------------------------------------------------- upload
def gcs_object_name(src: SourceFile) -> str:
    return f"hm/{DATA_VERSION}/{src.file_name}"


def upload(client: storage.Client, settings: Settings, src: SourceFile, local: Path) -> str:
    bucket = client.bucket(settings.raw_bucket)
    blob = bucket.blob(gcs_object_name(src))
    uri = f"gs://{settings.raw_bucket}/{blob.name}"

    if blob.exists():
        blob.reload()
        if blob.size == local.stat().st_size:
            print(f"  [skip] {uri} exists (same size)")
            return uri
        raise SystemExit(f"{uri} が既に存在しサイズが異なります。raw は不変なので DATA_VERSION を上げてください")

    size_mb = local.stat().st_size / 1024 / 1024
    print(f"  upload {local} ({size_mb:,.0f} MB) -> {uri}")
    if size_mb > 100:
        # 大きいファイルは並列チャンクアップロード
        transfer_manager.upload_chunks_concurrently(
            str(local), blob, chunk_size=64 * 1024 * 1024, max_workers=8
        )
    else:
        blob.upload_from_filename(str(local), timeout=600)
    return uri


# ---------------------------------------------------------------- load
def read_header_from_gcs(client: storage.Client, settings: Settings, src: SourceFile) -> list[str]:
    blob = client.bucket(settings.raw_bucket).blob(gcs_object_name(src))
    head = blob.download_as_bytes(start=0, end=64 * 1024)
    return parse_header(head)


def load_to_bq(
    bq: bigquery.Client, settings: Settings, src: SourceFile, columns: list[str]
) -> None:
    uri = f"gs://{settings.raw_bucket}/{gcs_object_name(src)}"
    table_id = settings.table("raw", src.table)
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=[bigquery.SchemaField(c, "STRING") for c in columns],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,  # articles.detail_desc に改行が含まれ得る
    )
    print(f"  load {uri} -> {table_id} ({len(columns)} cols)")
    job = bq.load_table_from_uri(uri, table_id, job_config=job_config, location=settings.region)
    job.result()
    table = bq.get_table(table_id)
    print(f"    rows={table.num_rows:,}")


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--project")
    parser.add_argument("--download-dir", type=Path, default=Path("data/raw/hm"))
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-load", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings(project_id=args.project)
    gcs = storage.Client(project=settings.project_id)
    bq = bigquery.Client(project=settings.project_id, location=settings.region)

    for src in SOURCES:
        print(f"== {src.file_name}")
        local = args.download_dir / src.file_name
        if not args.skip_download:
            local = download(settings.kaggle_competition, src, args.download_dir)
        if not args.skip_upload:
            upload(gcs, settings, src, local)
        if not args.skip_load:
            columns = read_header_from_gcs(gcs, settings, src)
            load_to_bq(bq, settings, src, columns)


if __name__ == "__main__":
    main()
