"""Tests for the personalized Simples tab and focus areas.

Runs standalone (``python tests/test_simples.py``) and under pytest, in the
style of the other tests here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import focus_areas as fa  # noqa: E402
import insight_style as ist  # noqa: E402
import simples  # noqa: E402

TIMEOUT = 60


def _frame(days: int = 60) -> pd.DataFrame:
    """Sleep rises by an hour in the last 30 days; mood is flat; stress unknown."""
    idx = pd.date_range("2026-08-21", periods=days, freq="D")
    rng = np.random.default_rng(1)
    recent = np.arange(days) >= days - 30
    return pd.DataFrame({
        "sleep_hours": np.where(recent, 7.5, 6.5) + rng.normal(0, 0.05, days),
        "sleep_score": np.where(recent, 85, 72) + rng.normal(0, 1, days),
        "resting_hr": np.where(recent, 55, 60) + rng.normal(0, 0.3, days),
        "mood": 6.0 + rng.normal(0, 0.01, days),
    }, index=idx)


# ── Period comparison ────────────────────────────────────────────────────────
def test_compare_detects_a_favorable_rise():
    f = simples.compare_periods(_frame(), 30, simples.METRIC_BY_KEY["sleep_hours"])
    assert f["direction"] == "up" and f["favorable"] is True
    assert abs(f["change"] - 1.0) < 0.1
    assert f["n_now"] == 30 and f["n_before"] == 30


def test_lower_resting_hr_counts_as_favorable():
    f = simples.compare_periods(_frame(), 30, simples.METRIC_BY_KEY["resting_hr"])
    assert f["direction"] == "down" and f["favorable"] is True


def test_small_change_reads_as_steady():
    f = simples.compare_periods(_frame(), 30, simples.METRIC_BY_KEY["mood"])
    assert f["direction"] == "steady"


def test_all_time_splits_the_record():
    f = simples.compare_periods(_frame(), None, simples.METRIC_BY_KEY["sleep_hours"])
    assert f["baseline"] == "the first half of your record"
    assert f["direction"] == "up"


def test_no_earlier_period_still_describes():
    f = simples.compare_periods(_frame(20), 30, simples.METRIC_BY_KEY["sleep_hours"])
    assert f["before"] is None and f["direction"] is None
    assert "averaged" in simples.describe(f, ist.INSIGHT_FOCUSED)


def test_missing_column_yields_nothing():
    assert simples.compare_periods(_frame(), 30, simples.METRIC_BY_KEY["hrv_avg"]) is None


def test_wording_differs_by_style():
    f = simples.compare_periods(_frame(), 30, simples.METRIC_BY_KEY["sleep_hours"])
    data = simples.describe(f, ist.DATA_DRIVEN)
    hybrid = simples.describe(f, ist.HYBRID)
    insight = simples.describe(f, ist.INSIGHT_FOCUSED)
    assert "n=30" in data and "%" in data
    assert "is up" in hybrid
    assert "minutes more a night" in insight and "n=" not in insight


# ── Focus areas ──────────────────────────────────────────────────────────────
def test_default_areas_follow_inquiry_priorities():
    assert fa.default_areas(["Improve sleep", "Manage stress"], _frame()) == [fa.SLEEP, fa.STRESS]


def test_default_areas_fall_back_to_available_data():
    df = _frame()[["mood"]]
    assert fa.default_areas([], df) == [fa.MOOD]


def test_columns_for_areas_are_ordered_and_unique():
    assert fa.columns_for([fa.MOOD, fa.SLEEP]) == [
        "mood", "feel_positive", "sleep_hours", "sleep_score"]


class _FakeDb:
    def __init__(self):
        self.row = {"focus_areas": None}

    def table(self, _):
        return self

    def select(self, *_):
        self._payload = None
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, *_):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if getattr(self, "_payload", None):
            self.row.update(self._payload)
        return type("R", (), {"data": [dict(self.row)]})()


def _picker_script():
    import streamlit as st

    import focus_areas

    with st.form("f"):
        focus_areas.render_focus_field(st.session_state["_db"], "user-1",
                                       ["Improve sleep"], st.session_state["_df"])
        st.form_submit_button("Save changes", on_click=focus_areas.save_from_picker,
                              args=(st.session_state["_db"], "user-1"))


def test_focus_picker_defaults_from_priorities_and_saves():
    db = _FakeDb()
    at = AppTest.from_function(_picker_script, default_timeout=TIMEOUT)
    at.session_state["_db"] = db
    at.session_state["_df"] = _frame()
    at.run()
    assert not at.exception
    assert at.multiselect[0].value == [fa.SLEEP]
    status = " ".join(c.value for c in at.caption)
    assert "**Sleep** · 60 days of data" in status
    assert "**Stress** · 60 days of data" in status   # resting HR counts
    at.multiselect[0].set_value([fa.MOOD, fa.STRESS]).run()
    assert db.row["focus_areas"] is None                # not until Save
    at.button[0].click().run()
    assert db.row["focus_areas"] == [fa.STRESS, fa.MOOD]


# ── The tab, through Streamlit's script runner ───────────────────────────────
def _tab_script():
    import streamlit as st

    import insights_data
    import simples

    insights_data.load_daily_frame = lambda *_: st.session_state["_df"]
    insights_data.load_priorities = lambda *_: []
    insights_data.table_available = lambda *_: True
    simples.render_simples_tab(None, "user-1")


def _run_tab(style, areas=("sleep",)):
    at = AppTest.from_function(_tab_script, default_timeout=TIMEOUT)
    at.session_state["_df"] = _frame()
    at.session_state["insight_style"] = style
    at.session_state["focus_areas"] = list(areas)
    return at.run()


def _text(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_data_driven_shows_full_charts_then_quick_insights():
    at = _run_tab(ist.DATA_DRIVEN)
    assert not at.exception
    assert at.radio[0].label == "View"
    assert at.radio[0].options == ["7-day average", "Daily"]
    assert at.radio[0].value == "7-day average"
    assert "7-day average" in _text(at)         # chart headlines follow it
    assert "Quick insights" in _text(at)
    assert [e.label for e in at.expander] == ["Other metrics"]


def test_hybrid_lists_findings_and_hides_full_data():
    at = _run_tab(ist.HYBRID)
    assert not at.exception
    assert "What changed" in _text(at) and "Trends" in _text(at)
    assert [e.label for e in at.expander] == ["See the full data"]
    assert at.expander[0].radio                 # full charts live inside
    assert at.expander[0].dataframe             # and the raw numbers


def test_insight_focused_leads_with_summary_and_cards():
    at = _run_tab(ist.INSIGHT_FOCUSED)
    assert not at.exception
    assert "In short" in _text(at)
    assert [e.label for e in at.expander] == ["Dive deeper"]
    research = [b for b in at.button if b.label == "Research — coming soon"]
    assert research and all(b.disabled for b in research)


def test_toggle_switches_the_layout():
    at = _run_tab(ist.DATA_DRIVEN)
    assert "Quick insights" in _text(at)
    at.button_group[0].set_value(ist.INSIGHT_FOCUSED).run()
    assert not at.exception
    assert "In short" in _text(at)
    assert at.session_state["insight_style"] == ist.INSIGHT_FOCUSED


def test_focus_areas_choose_the_metrics():
    at = _run_tab(ist.DATA_DRIVEN, areas=("mood",))
    labels = [m.value for m in at.markdown if 'class="section-label"' in m.value]
    assert any(">Mood<" in v for v in labels)
    assert not any(">Sleep<" in v for v in labels[:2])


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
