"""Tests for the onboarding pure logic (MIR-1: #43 inquiry + #16 profile).

Streamlit session state is stubbed, so these run without a Streamlit runtime:
    ./.venv-preview/bin/python tests/test_onboarding.py   (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import insight_inquiry  # noqa: E402
import profile_form  # noqa: E402


class _FakeSt:
    """Minimal stand-in for the streamlit module used by collect/validate."""

    def __init__(self, state=None):
        self.session_state = state or {}


def _stub(state: dict):
    fake = _FakeSt(state)
    insight_inquiry.st = fake
    profile_form.st = fake
    return fake


# ── insight_inquiry ──────────────────────────────────────────────────────────

def test_category_options_surfaces_suggestions():
    q = insight_inquiry.INQUIRY_QUESTIONS[0]  # improve
    base = insight_inquiry.category_options(q, [])
    assert base == q["categories"]
    with_sel = insight_inquiry.category_options(q, ["Improve sleep"])
    assert "Evening wind-down routine" in with_sel
    assert "Consistent wake time" in with_sel
    # selection itself always stays present
    assert "Improve sleep" in with_sel


def test_category_options_keeps_custom_selection():
    q = insight_inquiry.INQUIRY_QUESTIONS[0]
    opts = insight_inquiry.category_options(q, ["Something custom"])
    assert "Something custom" in opts


def test_collect_responses_shape_and_focus_filter():
    _stub({
        "inquiry_text_improve": "  sleep better  ",
        "inquiry_cats_improve": ["Improve sleep", "Manage stress"],
        "inquiry_focus_improve": ["Improve sleep", "NOT-SELECTED"],
        "inquiry_priorities": ["Improve sleep", "Manage stress", "Time management", "Extra"],
        "inquiry_period": "2 weeks",
    })
    r = insight_inquiry.collect_responses()
    assert r["improve"]["text"] == "sleep better"
    assert r["improve"]["categories"] == ["Improve sleep", "Manage stress"]
    # focus keeps only items that are actually selected
    assert r["improve"]["focus"] == ["Improve sleep"]
    # empty questions still present with empty values
    assert r["decrease"] == {"text": "", "categories": [], "focus": []}
    # priorities capped at PRIORITY_LIMIT, period passed through
    assert len(r["_priorities"]["top"]) == insight_inquiry.PRIORITY_LIMIT
    assert r["_priorities"]["period"] == "2 weeks"


def test_all_selected_categories_focus_first_no_dupes():
    _stub({
        "inquiry_cats_improve": ["A", "B"],
        "inquiry_focus_improve": ["B"],
        "inquiry_cats_decrease": ["B", "C"],
    })
    picked = insight_inquiry._all_selected_categories()
    assert picked[0] == "B"           # focus selections come first
    assert picked.count("B") == 1     # no duplicates
    assert set(picked) == {"A", "B", "C"}


# ── profile_form ─────────────────────────────────────────────────────────────

def test_collect_profile_normalizes_and_drops_empty():
    from datetime import date
    _stub({
        "profile_email": "  You@Example.COM ",
        "profile_phone": "(808) 555-1234",
        "profile_location": "  Honolulu ",
        "profile_timezone": "Pacific/Honolulu",
        "profile_date_of_birth": date(1990, 5, 1),
        "profile_sex": "Prefer not to say",
        "profile_gender_identity": "",
        "profile_occupation": "musician",
    })
    v = profile_form.collect_profile()
    assert v["email"] == "you@example.com"
    assert v["phone"] == "8085551234"
    assert v["location"] == "Honolulu"
    assert v["date_of_birth"] == "1990-05-01"
    assert v["occupation"] == "musician"
    # prefer-not-to-say and empty fields are dropped entirely
    assert "sex" not in v and "gender_identity" not in v


def test_validate_profile_flags_bad_email_and_phone():
    _stub({"profile_email": "not-an-email", "profile_phone": "123"})
    errors = profile_form.validate_profile()
    assert set(errors) == {"email", "phone"}


def test_validate_profile_ok_when_empty():
    _stub({})
    assert profile_form.validate_profile() == {}


def _run():
    fns = [g for n, g in sorted(globals().items()) if n.startswith("test_") and callable(g)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
