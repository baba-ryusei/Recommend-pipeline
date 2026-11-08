import zipfile

import pytest

from recsys.data import ingest_hm


def test_sanitize_column():
    assert ingest_hm.sanitize_column("t_dat") == "t_dat"
    assert ingest_hm.sanitize_column(" FN ") == "FN"
    assert ingest_hm.sanitize_column("colour group-code") == "colour_group_code"
    assert ingest_hm.sanitize_column("1st") == "_1st"
    with pytest.raises(ValueError):
        ingest_hm.sanitize_column("  ")


def test_parse_header_handles_bom_and_quotes():
    head = '﻿article_id,"prod_name",detail_desc\n0108775015,"Strap top","a, b"\n'.encode()
    assert ingest_hm.parse_header(head) == ["article_id", "prod_name", "detail_desc"]


def test_extract_single_member_only_writes_expected_file(tmp_path):
    zip_path = tmp_path / "articles.csv.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("articles.csv", "article_id\n1\n")
        zf.writestr("../evil.txt", "nope")
    target = tmp_path / "out" / "articles.csv"
    target.parent.mkdir()

    ingest_hm._extract_single_member(zip_path, "articles.csv", target)

    assert target.read_text() == "article_id\n1\n"
    assert not (tmp_path / "evil.txt").exists()


def test_extract_single_member_missing_member(tmp_path):
    zip_path = tmp_path / "x.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("other.csv", "a\n")
    with pytest.raises(SystemExit):
        ingest_hm._extract_single_member(zip_path, "articles.csv", tmp_path / "articles.csv")


def test_gcs_object_name_is_versioned():
    src = ingest_hm.SOURCES[0]
    assert ingest_hm.gcs_object_name(src) == f"hm/{ingest_hm.DATA_VERSION}/{src.file_name}"
