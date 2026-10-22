"""Tests for the Personalized Insights layouts (data-driven / hybrid /
insight-focused) over the unchanged k-means lenses.

Runs standalone (``python tests/test_personalized_insights.py``) and under
pytest, in the style of the other tests here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import insight_style as ist  # noqa: E402
import personalized_insights as pi  # noqa: E402

TIMEOUT = 90


def _frame(n: int = 40) -> pd.DataFrame:
    """Two clear sleep archetypes. Good-sleep nights also carry better mood and
    more activity (neither is a sleep-lens input), and fall on weekends."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-09-01", periods=n, freq="D")
    good = idx.dayofweek >= 4                 # Fri–Sun
    rem = np.where(good, 110, 70) + rng.normal(0, 4, n)
    rem[: n // 4] = np.nan                    # REM only on recent nights
    return pd.DataFrame({
        "sleep_score": np.where(good, 88, 60) + rng.normal(0, 2, n),
        "sleep_hours": np.where(good, 8.0, 5.5) + rng.normal(0, 0.2, n),
        "rem_sleep_min": rem,
        "deep_sleep_min": np.where(rng.random(n) < 0.3, 80, np.nan),  # sparse
        "hrv_avg": np.where(good, 60, 30) + rng.normal(0, 2, n),
        "resting_hr": np.where(good, 52, 66) + rng.normal(0, 1, n),
        "mood": np.where(good, 8.0, 5.5) + rng.normal(0, 0.3, n),
        "activity_score": np.where(good, 85, 70) + rng.normal(0, 2, n),
    }, index=idx)


# ── Model pieces ─────────────────────────────────────────────────────────────
def test_sparse_inputs_are_left_out_not_required():
    keep, dropped = pi._usable_features(pi.LENS_BY_KEY["sleep"], _frame())
    assert "rem_sleep_min" in keep            # 75% coverage: kept
    assert dropped == ["deep_sleep_min"]      # ~30%: dropped, and reported


def _model(k=None, quality=True):
    df = _frame()
    lens = pi.LENS_BY_KEY["sleep"]
    features, _ = pi._usable_features(lens, df)
    return pi._build_model(lens, df, df[features].dropna(), k, quality_names=quality)


def test_auto_k_finds_the_two_archetypes():
    model = _model()
    assert model.auto_k and model.k == 2
    assert model.silhouette > 0.5
    assert set(model.sweep) >= {2, 3}


def test_requested_k_is_honoured():
    model = _model(k=3)
    assert model.k == 3 and not model.auto_k
    assert len(model.order) == 3


def test_groups_are_ranked_and_named_by_quality():
    model = _model()
    best, worst = model.order
    assert model.names[best] == "Good-sleep days"
    assert model.names[worst] == "Poor-sleep days"
    best_days = model.assigned[model.assigned["_cluster"] == best]
    assert best_days["sleep_score"].mean() > 80


def test_middle_groups_get_the_middle_label():
    names = pi._quality_names(pi.LENS_BY_KEY["sleep"], [5, 6, 7])
    assert names == {5: "Good-sleep days", 6: "Middling-sleep days", 7: "Poor-sleep days"}


def test_linked_characteristics_come_from_outside_the_model():
    model = _model()
    links = pi._linked_characteristics(model)
    cols = [link["col"] for link in links]
    assert "mood" in cols and "activity_score" in cols
    assert not set(cols) & set(model.features)
    mood = next(link for link in links if link["col"] == "mood")
    sentence = pi._linked_sentence(model, mood)
    assert "points higher" in sentence and "good-sleep days" in sentence


def test_timing_notices_weekends():
    model = _model()
    assert "weekends" in pi._timing_note(model, model.order[0])


# ── Layouts, through Streamlit's script runner ───────────────────────────────
def _lens_script():
    import streamlit as st

    import personalized_insights as pi

    pi._render_kmeans_lens(pi.LENS_BY_KEY["sleep"], st.session_state["_df"],
                           st.session_state["_style"])


def _run(style):
    at = AppTest.from_function(_lens_script, default_timeout=TIMEOUT)
    at.session_state["_df"] = _frame()
    at.session_state["_style"] = style
    return at.run()


def _text(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_data_driven_layout():
    at = _run(ist.DATA_DRIVEN)
    assert not at.exception
    k_control = next(r for r in at.radio if r.label == "Number of groups")
    assert k_control.value == "Auto"
    text = _text(at)
    for section in ("Your days, grouped", "Quick insights", "The groups",
                    "Other measures by group", "Distribution by group",
                    "When each group happened"):
        assert section in text, section
    assert at.dataframe                       # mean (median) table
    assert at.selectbox[0].label == "Measure"     # histogram picker
    assert not at.expander
    assert "Left out because" in " ".join(c.value for c in at.caption)


def test_data_driven_k_override_reruns_the_model():
    at = _run(ist.DATA_DRIVEN)
    next(r for r in at.radio if r.label == "Number of groups").set_value("3").run()
    assert not at.exception
    assert "3 groups</strong> (set by you)" in _text(at)


def test_hybrid_layout():
    at = _run(ist.HYBRID)
    assert not at.exception
    text = _text(at)
    assert "K-means found <strong>2 kinds of sleep day</strong>" in text
    assert "What this suggests" in text
    assert [e.label for e in at.expander] == ["Dive deeper — see the full data"]
    assert at.expander[0].dataframe           # the data-driven page, inside
    assert not [r for r in at.radio if r.label == "Number of groups"]


def test_insight_focused_layout():
    at = _run(ist.INSIGHT_FOCUSED)
    assert not at.exception
    text = _text(at)
    assert "In short" in text and "Your groups" in text
    assert "GOOD-SLEEP DAYS" in text.upper()
    assert "What goes with it" in text and "points higher" in text
    research = [b for b in at.button if b.label == "Research — coming soon"]
    assert research and all(b.disabled for b in research)
    assert [e.label for e in at.expander] == ["Dive deeper"]


def _cycle_script():
    from datetime import date

    import streamlit as st

    import insights_data
    import personalized_insights as pi

    insights_data.load_cycle_starts = lambda *_: [
        date(2026, 8, 18), date(2026, 9, 15), date(2026, 10, 13)]
    pi._render_cycle_lens(None, "user-1", st.session_state["_df"],
                          st.session_state["_style"])


def test_cycle_lens_still_renders_in_every_style():
    for style in ist.STYLES:
        at = AppTest.from_function(_cycle_script, default_timeout=TIMEOUT)
        at.session_state["_df"] = _frame()
        at.session_state["_style"] = style
        at.run()
        assert not at.exception, style
        assert "Do your clusters follow your cycle?" in _text(at), style


def _tab_script():
    import streamlit as st

    import insights_data
    import personalized_insights as pi

    insights_data.load_daily_frame = lambda *_: st.session_state["_df"]
    insights_data.load_priorities = lambda *_: []
    pi.render_personalized_insights_tab(None, "user-1")


def test_tab_opens_on_focus_area_and_toggle_switches_layout():
    at = AppTest.from_function(_tab_script, default_timeout=TIMEOUT)
    at.session_state["_df"] = _frame()
    at.session_state["focus_areas"] = ["stress"]
    at.session_state["insight_style"] = ist.DATA_DRIVEN
    at.run()
    assert not at.exception
    assert at.selectbox(key="pi_lens").value == "stress"
    assert "Quick insights" in _text(at)
    at.button_group[0].set_value(ist.INSIGHT_FOCUSED).run()
    assert not at.exception
    assert "In short" in _text(at)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
