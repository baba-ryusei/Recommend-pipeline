from datetime import date

import pytest

from recsys.config import Settings
from recsys.data import build_stg
from recsys.sim import time_profile


def test_compute_anchor():
    anchor = build_stg.compute_anchor(date(2020, 9, 22), 28, date(2026, 11, 8))
    assert anchor.replay_start_dataset_date == date(2020, 8, 26)
    assert anchor.replay_end_dataset_date == date(2020, 9, 22)
    # リプレイ初日 + offset = 壁時計の基準日
    assert (
        date.fromordinal(anchor.replay_start_dataset_date.toordinal() + anchor.time_offset_days)
        == anchor.replay_start_wall_date
    )


def test_compute_anchor_rejects_non_positive_days():
    with pytest.raises(ValueError):
        build_stg.compute_anchor(date(2020, 9, 22), 0, date(2026, 11, 8))


def test_render_statements_substitutes_everything():
    settings = Settings(project_id="my-proj")
    anchor = build_stg.compute_anchor(date(2020, 9, 22), 28, date(2026, 11, 8))
    statements = build_stg.render_statements(settings, anchor)

    names = [name for name, _ in statements]
    assert names[0] == "sim_config"  # transactions が参照するので最初
    assert set(names) == {"sim_config", *build_stg.STG_TABLES}

    for _, sql_text in statements:
        assert "${" not in sql_text
        assert "`my-proj." in sql_text

    tx_sql = dict(statements)["transactions"]
    assert str(time_profile.hour_boundaries()) in tx_sql
    assert f"{anchor.time_offset_days} AS time_offset_days" in dict(statements)["sim_config"]
