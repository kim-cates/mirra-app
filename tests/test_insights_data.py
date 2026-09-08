"""Tests for the Simples / Personalized Insights data layer.

Runs standalone (``python tests/test_insights_data.py``) and under pytest, in
the style of the other tests here. Pure/offline — no network, no Supabase.

The cycle phase math is the reason this file exists: it is the one piece of
derived health data in the app, it is invisible to the eye once rendered, and a
silent off-by-one would mislabel every day in a phase.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import insights_data as idata  # noqa: E402

START = date(2026, 6, 1)
STARTS = [START, START + timedelta(days=28), START + timedelta(days=56)]


def _phase(offset_days, starts=STARTS, length=28):
    """Phase of the day `offset_days` after the last logged start."""
    return idata.cycle_day_and_phase(starts[-1] + timedelta(days=offset_days),
                                     starts, length)


# ── Cycle phases ─────────────────────────────────────────────────────────────
def test_first_day_is_cycle_day_one():
    assert _phase(0) == (1, "Menstrual")


def test_menstrual_covers_days_one_to_five():
    assert [_phase(i)[1] for i in range(5)] == ["Menstrual"] * 5


def test_follicular_starts_on_day_six():
    assert _phase(5) == (6, "Follicular")


def test_ovulatory_is_anchored_fourteen_days_before_next_start():
    # 28-day cycle → ovulation day 14, window 14–16.
    assert [_phase(i)[1] for i in (13, 14, 15)] == ["Ovulatory"] * 3
    assert _phase(12)[1] == "Follicular"
    assert _phase(16)[1] == "Luteal"


def test_ovulation_moves_with_a_longer_cycle():
    # A 35-day cycle keeps luteal at 14 days, so ovulation lands on day 21.
    assert _phase(19, length=35)[1] == "Follicular"
    assert _phase(20, length=35)[1] == "Ovulatory"
    assert _phase(23, length=35)[1] == "Luteal"


def test_short_cycle_does_not_push_ovulation_into_menstruation():
    # A 17-day cycle would put ovulation on day 3 without the floor.
    day, phase = _phase(2, length=17)
    assert (day, phase) == (3, "Menstrual")


def test_stale_log_yields_no_phase():
    """Past a plausible cycle length the log has gone stale — don't guess."""
    assert _phase(60) == (None, None)


def test_days_before_the_first_log_are_unlabelled():
    assert idata.cycle_day_and_phase(START - timedelta(days=1), STARTS) == (None, None)


def test_median_cycle_length_from_logs():
    assert idata.median_cycle_length(STARTS) == 28
    irregular = [START, START + timedelta(days=26), START + timedelta(days=56)]
    assert idata.median_cycle_length(irregular) == 28  # median of 26 and 30


def test_median_ignores_implausible_gaps():
    """A forgotten cycle leaves a 90-day gap that is not a cycle length."""
    gappy = [START, START + timedelta(days=30), START + timedelta(days=120)]
    assert idata.median_cycle_length(gappy) == 30


def test_median_falls_back_to_default():
    assert idata.median_cycle_length([]) == idata.DEFAULT_CYCLE_LENGTH
    assert idata.median_cycle_length([START]) == idata.DEFAULT_CYCLE_LENGTH


def test_add_cycle_phase_without_logs_is_all_null():
    df = pd.DataFrame(index=pd.date_range("2026-06-01", periods=10, freq="D"))
    out = idata.add_cycle_phase(df, [])
    assert out["cycle_phase"].isna().all()
    assert out["cycle_day"].isna().all()


# ── Productivity proxy ───────────────────────────────────────────────────────
def test_productivity_uses_self_reported_focus():
    feelings = [{"name": "focused", "intensity": 9}]
    assert idata._productivity_proxy("", None, feelings) == 9.0


def test_productivity_reads_language_when_no_rating():
    high = idata._productivity_proxy("shipped it, made headway", None, None)
    low = idata._productivity_proxy("procrastinated and felt stuck", None, None)
    assert high is not None and low is not None
    assert high > low


def test_productivity_is_none_without_evidence():
    """A day with no focus rating and no cue words scores nothing, not a bland 5."""
    assert idata._productivity_proxy("had lunch outside", None, None) is None
    assert idata._productivity_proxy(None, None, None) is None


def test_productivity_averages_both_signals():
    # Rating 3 (low) against clearly productive language (10) → the middle.
    score = idata._productivity_proxy("finished and shipped it", None,
                                      [{"name": "focused", "intensity": 3}])
    assert 5.5 < score < 7.5


def test_productivity_reads_keywords_too():
    assert idata._productivity_proxy("", ["procrastinated"], None) is not None


# ── Feelings ─────────────────────────────────────────────────────────────────
def test_feeling_stats_splits_polarity():
    pos, neg, count, mean = idata._feeling_stats([
        {"name": "calm", "intensity": 8},
        {"name": "anxious", "intensity": 4},
    ])
    assert (pos, neg, count) == (8.0, 4.0, 2)
    assert mean == 6.0


def test_unrated_feeling_counts_at_the_midpoint():
    """`intensity: null` means "felt it, didn't rate it" — not "didn't feel it"."""
    pos, _, count, _ = idata._feeling_stats([{"name": "calm", "intensity": None}])
    assert count == 1 and pos == 5.5


def test_neutral_belongs_to_neither_pole():
    pos, neg, count, _ = idata._feeling_stats([{"name": "neutral", "intensity": 6}])
    assert (pos, neg, count) == (0.0, 0.0, 1)


def test_no_feelings_is_all_none():
    assert idata._feeling_stats([]) == (None, None, 0, None)
    assert idata._feeling_stats(None) == (None, None, 0, None)


def test_malformed_feelings_do_not_crash():
    pos, neg, count, _ = idata._feeling_stats(["not a dict", {"name": "calm"}])
    assert count == 1 and pos == 5.5


# ── Priorities ───────────────────────────────────────────────────────────────
def test_priorities_map_to_lens_keys():
    assert idata.priority_lens_keys(["Sleep quality"]) == ["sleep"]
    assert "productivity" in idata.priority_lens_keys(["Career focus"])
    assert "cycle" in idata.priority_lens_keys(["Understanding my hormones"])


def test_unmatched_priority_forces_no_lens():
    assert idata.priority_lens_keys(["Learning Portuguese"]) == []


# ── Windowing ────────────────────────────────────────────────────────────────
def test_window_slices_from_the_most_recent_day():
    df = pd.DataFrame({"x": range(60)},
                      index=pd.date_range("2026-01-01", periods=60, freq="D"))
    assert len(idata.apply_window(df, 30)) == 30
    assert len(idata.apply_window(df, None)) == 60
    assert idata.apply_window(df, 30).index.max() == df.index.max()


def test_coverage_counts_only_present_values():
    df = pd.DataFrame({"x": [1.0, None, 3.0]},
                      index=pd.date_range("2026-01-01", periods=3, freq="D"))
    assert idata.coverage(df, "x") == 2
    assert idata.coverage(df, "missing_column") == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
