"""Tests for Spotify recently-played aggregation (MIR-3 #28).

Runs standalone (``python3 tests/test_spotify_sync.py``) and under pytest.
Pure/offline — exercises the row-mapping, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.spotify import aggregate_recently_played  # noqa: E402

TZ = "Pacific/Honolulu"  # UTC-10, so late-UTC plays fall on the prior local day


def _play(played_at, track_id, artist_ids, duration_ms):
    return {
        "played_at": played_at,
        "track": {
            "id": track_id,
            "duration_ms": duration_ms,
            "artists": [{"id": a} for a in artist_ids],
        },
    }


# Two plays that land on 2026-08-13 (HST) + two on 2026-08-14 (HST).
SAMPLE = [
    _play("2026-08-14T05:00:00Z", "t1", ["a1"], 180_000),        # HST 2026-08-13 19:00
    _play("2026-08-14T07:30:00Z", "t2", ["a1", "a2"], 200_000),  # HST 2026-08-13 21:30
    _play("2026-08-14T20:00:00Z", "t3", ["a3"], 150_000),        # HST 2026-08-14 10:00
    _play("2026-08-14T21:00:00Z", "t1", ["a1"], 180_000),        # HST 2026-08-14 11:00
]


def test_groups_by_local_day():
    out = aggregate_recently_played(SAMPLE, TZ)
    assert set(out) == {"2026-08-13", "2026-08-14"}, out


def test_counts_and_unique_artists():
    out = aggregate_recently_played(SAMPLE, TZ)
    d13 = out["2026-08-13"]
    assert d13["track_count"] == 2
    assert d13["unique_artists"] == 2          # a1, a2 (a1 appears twice)
    assert d13["listening_ms"] == 380_000


def test_no_features_omits_audio_keys():
    out = aggregate_recently_played(SAMPLE, TZ)
    assert "valence" not in out["2026-08-14"]


def test_features_averaged_when_provided():
    features = {
        "t3": {"valence": 0.6, "energy": 0.8, "tempo": 120.0},
        "t1": {"valence": 0.4, "energy": 0.6, "tempo": 100.0},
    }
    out = aggregate_recently_played(SAMPLE, TZ, features_by_id=features)
    d14 = out["2026-08-14"]  # tracks t3 + t1
    assert d14["valence"] == 0.5      # mean(0.6, 0.4)
    assert d14["energy"] == 0.7
    assert d14["tempo"] == 110.0


def test_missing_feature_value_is_none_not_crash():
    features = {"t3": {"valence": 0.6}, "t1": {"valence": None}}  # t1 valence missing
    out = aggregate_recently_played(SAMPLE, TZ, features_by_id=features)
    assert out["2026-08-14"]["valence"] == 0.6   # only t3 counted
    assert out["2026-08-14"]["tempo"] is None    # no tempo anywhere


def test_empty_input():
    assert aggregate_recently_played([], TZ) == {}


def test_skips_items_without_played_at():
    bad = [{"track": {"id": "x"}}]  # no played_at
    assert aggregate_recently_played(bad, TZ) == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
