"""Tests for the Fitbit daily rollup (MIR-3, fourth connector).

Runs standalone (``python3 tests/test_fitbit_sync.py``) and under pytest.
Pure/offline — exercises the row-mapping, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.fitbit import aggregate_fitbit_daily  # noqa: E402


def _sleep(day, main=True, asleep=420, stages=True):
    log = {
        "dateOfSleep": day,
        "isMainSleep": main,
        "minutesAsleep": asleep,
        "minutesAwake": 40,
        "timeInBed": asleep + 40,
        "efficiency": 94,
        "levels": {"summary": {
            "deep": {"minutes": 60, "count": 4},
            "light": {"minutes": 240, "count": 19},
            "rem": {"minutes": 120, "count": 8},
            "wake": {"minutes": 40, "count": 21},
        }},
    }
    if not stages:
        # Classic log from an older tracker: asleep/awake/restless, no stages.
        log["levels"] = {"summary": {
            "asleep": {"minutes": 420, "count": 1},
            "restless": {"minutes": 30, "count": 5},
            "awake": {"minutes": 10, "count": 2},
        }}
    return log


def test_main_sleep_maps_stage_minutes():
    out = aggregate_fitbit_daily([_sleep("2026-08-14")], [], [], [])
    row = out["2026-08-14"]
    assert row["minutes_asleep"] == 420
    assert row["minutes_deep"] == 60
    assert row["minutes_rem"] == 120
    assert row["sleep_efficiency"] == 94
    assert row["nap_count"] == 0


def test_classic_log_keeps_duration_but_no_stages():
    out = aggregate_fitbit_daily([_sleep("2026-08-14", stages=False)], [], [], [])
    row = out["2026-08-14"]
    assert row["minutes_asleep"] == 420
    assert row["minutes_deep"] is None
    assert row["minutes_light"] is None


def test_extra_logs_counted_as_naps():
    logs = [_sleep("2026-08-14"),
            _sleep("2026-08-14", main=False, asleep=45)]
    row = aggregate_fitbit_daily(logs, [], [], [])["2026-08-14"]
    assert row["nap_count"] == 1
    assert row["minutes_asleep"] == 420          # the nap must not overwrite it


def test_nap_before_main_sleep_still_leaves_main_metrics():
    logs = [_sleep("2026-08-14", main=False, asleep=45),
            _sleep("2026-08-14")]
    row = aggregate_fitbit_daily(logs, [], [], [])["2026-08-14"]
    assert row["nap_count"] == 1
    assert row["minutes_asleep"] == 420


def test_resting_hr_and_hrv_join_the_same_day():
    heart = [{"dateTime": "2026-08-14",
              "value": {"restingHeartRate": 58, "heartRateZones": []}}]
    hrv = [{"dateTime": "2026-08-14",
            "value": {"dailyRmssd": 42.1, "deepRmssd": 47.3}}]
    row = aggregate_fitbit_daily([_sleep("2026-08-14")], heart, hrv, [])["2026-08-14"]
    assert row["resting_heart_rate"] == 58
    assert row["hrv_daily_rmssd"] == 42.1
    assert row["hrv_deep_rmssd"] == 47.3


def test_day_without_resting_hr_is_not_created_by_heart_zones_alone():
    heart = [{"dateTime": "2026-08-15", "value": {"heartRateZones": []}}]
    out = aggregate_fitbit_daily([], heart, [], [])
    assert out == {}


def test_steps_string_value_becomes_int():
    steps = [{"dateTime": "2026-08-14", "value": "8231"},
             {"dateTime": "2026-08-15", "value": "not-a-number"}]
    out = aggregate_fitbit_daily([], [], [], steps)
    assert out["2026-08-14"]["steps"] == 8231
    assert "2026-08-15" not in out


def test_separate_days_stay_separate():
    out = aggregate_fitbit_daily([_sleep("2026-08-14"), _sleep("2026-08-15")],
                                 [], [], [{"dateTime": "2026-08-15", "value": "100"}])
    assert set(out) == {"2026-08-14", "2026-08-15"}
    assert "steps" not in out["2026-08-14"]


def test_raw_keeps_original_payloads():
    heart = [{"dateTime": "2026-08-14", "value": {"restingHeartRate": 58}}]
    row = aggregate_fitbit_daily([_sleep("2026-08-14")], heart, [], [])["2026-08-14"]
    assert set(row["raw"]) == {"sleep", "heart"}


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
