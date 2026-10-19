"""Tests for the insight-style setting (data-driven / hybrid / insight-focused).

Runs standalone (``python tests/test_insight_style.py``) and under pytest, in
the style of the other tests here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest  # noqa: E402

import insight_style as ist  # noqa: E402


# ── Fakes ────────────────────────────────────────────────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, raises):
        self.store, self.raises, self.payload = store, raises, None

    def select(self, *_):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, *_):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self.raises:
            raise RuntimeError('column "insight_style" does not exist')
        if self.payload is not None:
            self.store.update(self.payload)
        return _Result([dict(self.store)])


class FakeSupabase:
    def __init__(self, row=None, raises=False):
        self.row = dict(row or {})
        self.raises = raises

    def table(self, _name):
        return _Query(self.row, self.raises)


# ── Pure helpers ─────────────────────────────────────────────────────────────
def test_normalize_falls_back_to_hybrid():
    assert ist.normalize("data_driven") == ist.DATA_DRIVEN
    assert ist.normalize(None) == ist.HYBRID
    assert ist.normalize("nonsense") == ist.HYBRID


def test_every_style_has_label_description_and_prompt():
    for style in ist.STYLES:
        assert ist.LABELS[style]
        assert ist.DESCRIPTIONS[style]
        assert ist.prompt_guidance(style)
    assert "DATA-DRIVEN" in ist.prompt_guidance(ist.DATA_DRIVEN)
    assert "INSIGHT-FOCUSED" in ist.prompt_guidance(ist.INSIGHT_FOCUSED)


# ── Profile form + Simples toggle, driven through Streamlit's script runner ──
def _settings_script():
    """Simples' toggle, then Profile's Personalization form, as in the app."""
    import pandas as pd
    import streamlit as st

    import insight_style
    import insights_data
    import profile_tab

    insights_data.load_priorities = lambda *_: []
    insights_data.load_daily_frame = lambda *_: pd.DataFrame()
    db = st.session_state["_fake_db"]
    insight_style.render_style_toggle(db, "user-1")
    profile_tab._render_personalization_section(db, "user-1")


def _run_settings(db):
    at = AppTest.from_function(_settings_script, default_timeout=30)
    at.session_state["_fake_db"] = db
    return at.run()


def _save(at):
    return next(b for b in at.button if b.label == "Save changes").click().run()


def test_form_loads_saved_style():
    at = _run_settings(FakeSupabase({"insight_style": "insight_focused"}))
    assert not at.exception
    assert at.radio[0].value == ist.INSIGHT_FOCUSED


def test_form_saves_only_when_save_is_clicked():
    db = FakeSupabase({"insight_style": "hybrid"})
    at = _run_settings(db)
    at.radio[0].set_value(ist.DATA_DRIVEN)
    at.multiselect[0].set_value(["mood"])
    assert db.row["insight_style"] == ist.HYBRID      # nothing written yet
    _save(at)
    assert db.row["insight_style"] == ist.DATA_DRIVEN
    assert db.row["focus_areas"] == ["mood"]
    assert at.success and not at.warning


def test_form_warns_but_keeps_choice_before_migration():
    at = _run_settings(FakeSupabase(raises=True))
    assert at.radio[0].value == ist.HYBRID      # default when column is missing
    at.radio[0].set_value(ist.INSIGHT_FOCUSED)
    _save(at)
    assert at.session_state["insight_style"] == ist.INSIGHT_FOCUSED
    assert at.warning and not at.success


def test_toggle_and_form_stay_in_sync():
    db = FakeSupabase({"insight_style": "hybrid"})
    at = _run_settings(db)
    at.button_group[0].set_value(ist.DATA_DRIVEN).run()
    assert at.radio[0].value == ist.DATA_DRIVEN
    assert db.row["insight_style"] == ist.DATA_DRIVEN
    at.radio[0].set_value(ist.INSIGHT_FOCUSED)
    _save(at)
    assert not at.exception
    assert at.button_group[0].value == ist.INSIGHT_FOCUSED
    assert db.row["insight_style"] == ist.INSIGHT_FOCUSED


def test_clicking_the_active_toggle_off_keeps_the_style():
    at = _run_settings(FakeSupabase({"insight_style": "hybrid"}))
    at.button_group[0].set_value(None).run()
    assert at.button_group[0].value == ist.HYBRID
    assert at.session_state["insight_style"] == ist.HYBRID


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
