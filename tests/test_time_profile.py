from recsys.sim import time_profile


def test_weights_sum_to_resolution():
    assert len(time_profile.HOURLY_WEIGHTS_PERMILLE) == 24
    assert sum(time_profile.HOURLY_WEIGHTS_PERMILLE) == time_profile.BUCKET_RESOLUTION


def test_boundaries_are_strictly_increasing_and_23_long():
    b = time_profile.hour_boundaries()
    assert len(b) == 23
    assert all(x < y for x, y in zip(b, b[1:], strict=False))
    assert b[-1] < time_profile.BUCKET_RESOLUTION


def test_hour_for_bucket_matches_range_bucket_semantics():
    b = time_profile.hour_boundaries()
    assert time_profile.hour_for_bucket(0) == 0
    assert time_profile.hour_for_bucket(b[0] - 1) == 0
    # 境界値ちょうどは次の時間帯（RANGE_BUCKET と同じ）
    assert time_profile.hour_for_bucket(b[0]) == 1
    assert time_profile.hour_for_bucket(time_profile.BUCKET_RESOLUTION - 1) == 23


def test_bucket_distribution_reproduces_weights():
    counts = [0] * 24
    for bucket in range(time_profile.BUCKET_RESOLUTION):
        counts[time_profile.hour_for_bucket(bucket)] += 1
    assert tuple(counts) == time_profile.HOURLY_WEIGHTS_PERMILLE
