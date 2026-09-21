"""Tests for the Strava daily rollup (MIR-3, fifth connector).

Runs standalone (``python3 tests/test_strava_sync.py``) and under pytest.
Pure/offline — exercises the row-mapping, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.strava import aggregate_strava_daily  # noqa: E402


def _run(day="2026-09-14", start="07:31:12", moving=3600, sport="Run", **extra):
    act = {
        "id": 1234567890,
        "name": "Morning Run",
        "sport_type": sport,
        "type": sport,
        "start_date": f"{day}T{start}Z",
        "start_date_local": f"{day}T{start}Z",
        "moving_time": moving,
        "elapsed_time": moving + 300,
        "distance": 10000.0,
        "total_elevation_gain": 120.5,
        "average_heartrate": 152.4,
        "max_heartrate": 181.0,
        "suffer_score": 64.0,
        "map": {"summary_polyline": "must_not_survive"},
        "start_latlng": [21.3, -157.8],
        "end_latlng": [21.3, -157.8],
    }
    act.update(extra)
    return act


def test_single_activity_maps_all_columns():
    row = aggregate_strava_daily([_run()])["2026-09-14"]
    assert row["activity_count"] == 1
    assert row["moving_minutes"] == 60
    assert row["elapsed_minutes"] == 65
    assert row["distance_km"] == 10.0
    assert row["elevation_gain_m"] == 120.5
    assert row["relative_effort"] == 64.0
    assert row["main_sport_type"] == "Run"
    assert row["sport_types"] == "Run"
    assert row["average_heartrate"] == 152.4
    assert row["max_heartrate"] == 181.0


def test_two_activities_same_day_sum_and_longest_wins_hr():
    acts = [_run(moving=3600, sport="Run"),
            _run(start="18:02:00", moving=1800, sport="Ride",
                 average_heartrate=120.0, max_heartrate=140.0, suffer_score=20.0)]
    row = aggregate_strava_daily(acts)["2026-09-14"]
    assert row["activity_count"] == 2
    assert row["moving_minutes"] == 90
    assert row["distance_km"] == 20.0
    assert row["relative_effort"] == 84.0
    assert row["main_sport_type"] == "Run"           # 3600s beats 1800s
    assert row["sport_types"] == "Run,Ride"
    assert row["average_heartrate"] == 152.4          # from the main activity only


def test_separate_days_stay_separate():
    out = aggregate_strava_daily([_run("2026-09-14"), _run("2026-09-15")])
    assert set(out) == {"2026-09-14", "2026-09-15"}
    assert out["2026-09-15"]["activity_count"] == 1


def test_activity_without_local_start_is_skipped():
    broken = _run()
    broken["start_date_local"] = None
    assert aggregate_strava_daily([broken]) == {}


def test_nullable_extras_stay_none_when_absent():
    manual = _run(suffer_score=None, average_heartrate=None, max_heartrate=None)
    manual.pop("kilojoules", None)
    row = aggregate_strava_daily([manual])["2026-09-14"]
    assert row["relative_effort"] is None
    assert row["kilojoules"] is None
    assert row["average_heartrate"] is None


def test_kilojoules_sum_ignores_activities_without_them():
    acts = [_run(sport="Ride", kilojoules=500.0),
            _run(start="18:00:00", moving=600, sport="Run")]  # runs carry no kJ
    row = aggregate_strava_daily(acts)["2026-09-14"]
    assert row["kilojoules"] == 500.0


def test_raw_is_trimmed_of_gps_and_map():
    row = aggregate_strava_daily([_run()])["2026-09-14"]
    kept = row["raw"]["activities"][0]
    assert kept["name"] == "Morning Run"
    assert "map" not in kept
    assert "start_latlng" not in kept
    assert "end_latlng" not in kept


def test_missing_numeric_fields_count_as_zero_in_sums():
    bare = {"start_date_local": "2026-09-14T07:00:00Z", "sport_type": "Yoga"}
    row = aggregate_strava_daily([bare])["2026-09-14"]
    assert row["moving_minutes"] == 0
    assert row["distance_km"] == 0.0
    assert row["main_sport_type"] == "Yoga"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
