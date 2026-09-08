"""Tests for Whoop day attribution and rollup (MIR-3, third connector).

Runs standalone (``python3 tests/test_whoop_sync.py``) and under pytest.
Pure/offline — exercises the row-mapping, no network.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.whoop import aggregate_whoop_daily  # noqa: E402


def _sleep(sid, start, end, offset="-10:00", nap=False, in_bed=8 * 3600_000,
           scored=True, performance=90.0):
    return {
        "id": sid,
        "start": start,
        "end": end,
        "timezone_offset": offset,
        "nap": nap,
        "score_state": "SCORED" if scored else "PENDING_SCORE",
        "score": {
            "sleep_performance_percentage": performance,
            "sleep_efficiency_percentage": 92.0,
            "sleep_consistency_percentage": 70.0,
            "respiratory_rate": 14.5,
            "stage_summary": {
                "total_in_bed_time_milli": in_bed,
                "total_awake_time_milli": 600_000,
                "total_light_sleep_time_milli": 4 * 3600_000,
                "total_slow_wave_sleep_time_milli": 2 * 3600_000,
                "total_rem_sleep_time_milli": 2 * 3600_000,
                "sleep_cycle_count": 5,
                "disturbance_count": 3,
            },
        },
    }


def _recovery(sleep_id, created_at, score=66, scored=True):
    return {
        "sleep_id": sleep_id,
        "created_at": created_at,
        "score_state": "SCORED" if scored else "PENDING_SCORE",
        "score": {
            "recovery_score": score,
            "hrv_rmssd_milli": 55.5,
            "resting_heart_rate": 52,
            "spo2_percentage": 97.0,
            "skin_temp_celsius": 33.1,
        },
    }


def _cycle(start, offset="-10:00", strain=12.5):
    return {
        "start": start,
        "timezone_offset": offset,
        "score_state": "SCORED",
        "score": {"strain": strain, "kilojoule": 9000.0,
                  "average_heart_rate": 70, "max_heart_rate": 150},
    }


# Sleep ends 2026-08-14T16:30Z = 06:30 local at UTC-10 -> the day is 2026-08-14.
MAIN_SLEEP = _sleep("s1", "2026-08-14T06:00:00Z", "2026-08-14T16:30:00Z")


def test_sleep_attributed_to_local_wake_day():
    out = aggregate_whoop_daily([], [MAIN_SLEEP], [])
    assert set(out) == {"2026-08-14"}, out
    assert out["2026-08-14"]["sleep_performance_percentage"] == 90.0
    assert out["2026-08-14"]["total_in_bed_time_milli"] == 8 * 3600_000


def test_offset_moves_the_day_back():
    """Same UTC end, member in UTC-10: 2026-08-15T06:00Z is still the 14th there."""
    late = _sleep("s2", "2026-08-14T20:00:00Z", "2026-08-15T06:00:00Z")
    out = aggregate_whoop_daily([], [late], [])
    assert set(out) == {"2026-08-14"}, out


def test_recovery_inherits_its_sleep_day():
    # created_at is the next UTC day; it must still land on the sleep's day.
    rec = _recovery("s1", "2026-08-15T17:00:00Z")
    out = aggregate_whoop_daily([rec], [MAIN_SLEEP], [])
    assert set(out) == {"2026-08-14"}, out
    assert out["2026-08-14"]["recovery_score"] == 66
    assert out["2026-08-14"]["hrv_rmssd_milli"] == 55.5


def test_recovery_without_matching_sleep_falls_back_to_created_at():
    rec = _recovery("unknown", "2026-08-14T17:00:00Z")   # 07:00 local, UTC-10
    out = aggregate_whoop_daily([rec], [], [])
    assert set(out) == {"2026-08-14"}, out


def test_naps_counted_not_merged():
    nap = _sleep("s3", "2026-08-14T23:00:00Z", "2026-08-15T00:00:00Z", nap=True)
    out = aggregate_whoop_daily([], [MAIN_SLEEP, nap], [])
    assert out["2026-08-14"]["nap_count"] == 1
    # The nap must not overwrite the main sleep's numbers.
    assert out["2026-08-14"]["sleep_performance_percentage"] == 90.0


def test_longest_sleep_wins_the_day():
    short = _sleep("s4", "2026-08-14T05:00:00Z", "2026-08-14T15:00:00Z",
                   in_bed=3 * 3600_000, performance=40.0)
    out = aggregate_whoop_daily([], [short, MAIN_SLEEP], [])
    assert out["2026-08-14"]["sleep_performance_percentage"] == 90.0
    out_reversed = aggregate_whoop_daily([], [MAIN_SLEEP, short], [])
    assert out_reversed["2026-08-14"]["sleep_performance_percentage"] == 90.0


def test_unscored_record_makes_a_row_without_metrics():
    pending = _sleep("s5", "2026-08-14T06:00:00Z", "2026-08-14T16:30:00Z", scored=False)
    out = aggregate_whoop_daily([], [pending], [])
    assert set(out) == {"2026-08-14"}
    assert "sleep_performance_percentage" not in out["2026-08-14"]


def test_cycle_strain_lands_on_start_day_and_keeps_the_highest():
    cycles = [_cycle("2026-08-14T14:00:00Z", strain=8.0),      # 04:00 local
              _cycle("2026-08-14T20:00:00Z", strain=15.2)]     # 10:00 local
    out = aggregate_whoop_daily([], [], cycles)
    assert out["2026-08-14"]["strain"] == 15.2
    assert out["2026-08-14"]["max_heart_rate"] == 150


def test_raw_keeps_original_payloads():
    out = aggregate_whoop_daily([_recovery("s1", "2026-08-15T17:00:00Z")],
                                [MAIN_SLEEP], [_cycle("2026-08-14T20:00:00Z")])
    raw = out["2026-08-14"]["raw"]
    assert set(raw) == {"sleep", "recovery", "cycle"}


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
