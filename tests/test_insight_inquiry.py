"""Tests for the insight-inquiry wizard's storage (MIR-1 #43).

Runs standalone (``python tests/test_insight_inquiry.py``) and under pytest, in
the style of the other tests here.

These exist because of a bug that was invisible in review and nearly invisible
in use: Streamlit garbage-collects a widget's session_state entry one rerun
after the widget stops being rendered, and the wizard shows one question per
page. Reading the widget keys at save time therefore returned empty strings for
every page but the last, and what reached users.inquiry_responses was a
structurally perfect object with every answer blank -- which the Profile tab
then correctly reported as "you have not answered the insight questions yet".

So these tests drive the real wizard through Streamlit's own script runner.
A unit test that pokes session_state directly cannot catch this: the culling is
the runtime's behaviour, not ours.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest  # noqa: E402

import insight_inquiry as iq  # noqa: E402

ANSWERS = [
    ("Sleep earlier and protect my mornings.", ["Improve sleep", "Manage stress"]),
    ("Less doomscrolling before bed.", ["Doomscrolling / screen time", "Late nights"]),
    ("Ship the app and stay healthy.", ["Career growth", "Health & fitness"]),
    ("Phone in the other room.", ["Social media", "Multitasking"]),
]

BACK_LABEL = "Back"


# ── The script under test ────────────────────────────────────────────────────
def _wizard_script():
    """Mount the wizard exactly as the Profile tab's retake path does."""
    import streamlit as st

    import insight_inquiry as inquiry

    saved = st.session_state.setdefault("_saved", [])
    matches = st.session_state.get("_db_matches", True)

    class _Table:
        def __init__(self):
            self.payload = None

        def update(self, payload):
            self.payload = payload
            return self

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def execute(self):
            if self.payload is None:
                return type("R", (), {"data": []})
            saved.append(self.payload)
            return type("R", (), {"data": [self.payload] if matches else []})

    class _Client:
        def table(self, name):
            return _Table()

    seed = st.session_state.pop("_seed_from", None)
    if seed is not None:
        inquiry.seed_widget_state(seed)

    inquiry.render_insight_inquiry(_Client(), "u1", mode="edit")
    st.session_state["_collected"] = inquiry.collect_responses()


def _state(at, key, default=None):
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _button(at, label):
    return [b for b in at.button if label in b.label]


def _fill_all(at):
    """Answer every question, advancing a page each time."""
    for text, categories in ANSWERS:
        at.text_area[0].set_value(text).run()
        at.multiselect[0].set_value(categories).run()
        if len(at.multiselect) > 1:          # focus picker appears at >1 category
            at.multiselect[1].set_value(categories[:1]).run()
        nxt = _button(at, "Next")
        if nxt:
            nxt[0].click().run()
    return at


def _fresh(**session):
    at = AppTest.from_function(_wizard_script, default_timeout=120)
    for key, value in session.items():
        at.session_state[key] = value
    at.run()
    return at


# ── The regression ───────────────────────────────────────────────────────────
def test_first_answer_survives_to_the_final_page():
    """The bug: page 1's answer was gone two pages later."""
    at = _fresh()
    at.text_area[0].set_value("Sleep earlier.").run()
    at.multiselect[0].set_value(["Improve sleep"]).run()
    for _ in range(3):
        nxt = _button(at, "Next")
        if nxt:
            nxt[0].click().run()
    collected = _state(at, "_collected", {})
    assert collected["improve"]["text"] == "Sleep earlier.", collected["improve"]
    assert collected["improve"]["categories"] == ["Improve sleep"]


def test_every_answer_reaches_the_save_payload():
    at = _fill_all(_fresh())
    collected = _state(at, "_collected", {})
    for (text, categories), question in zip(ANSWERS, iq.INQUIRY_QUESTIONS):
        answer = collected[question["key"]]
        assert answer["text"] == text, question["key"]
        assert answer["categories"] == categories, question["key"]
        assert answer["focus"] == categories[:1], question["key"]


def test_priorities_page_offers_the_earlier_selections():
    """Second symptom of the same cause: nothing to pick priorities from."""
    at = _fill_all(_fresh())
    assert at.multiselect, "priorities multiselect was not rendered"
    options = list(at.multiselect[0].options)
    for _, categories in ANSWERS:
        for category in categories:
            assert category in options, f"{category} missing from {options}"


def test_focus_selections_are_offered_first():
    """Focus picks lead the priorities list -- they are the stronger signal."""
    at = _fill_all(_fresh())
    options = list(at.multiselect[0].options)
    focused = [categories[0] for _, categories in ANSWERS]
    assert options[:len(focused)] == focused, options


def test_saved_payload_is_complete():
    at = _fill_all(_fresh())
    at.multiselect[0].set_value(["Improve sleep", "Career growth"]).run()
    at.radio[0].set_value("2 weeks").run()
    _button(at, "Save")[0].click().run()

    payload = _state(at, "_saved", [])[-1]
    assert "inquiry_completed_at" in payload
    responses = payload["inquiry_responses"]
    assert responses["improve"]["text"] == ANSWERS[0][0]
    assert responses["distractions"]["text"] == ANSWERS[3][0]
    assert responses["_priorities"] == {
        "top": ["Improve sleep", "Career growth"],
        "period": "2 weeks",
    }


def test_going_back_restores_the_answer():
    at = _fresh()
    at.text_area[0].set_value("Answer one.").run()
    at.multiselect[0].set_value(["Improve sleep", "Manage stress"]).run()
    _button(at, "Next")[0].click().run()
    _button(at, "Next")[0].click().run()          # two pages away: state is culled
    _button(at, BACK_LABEL)[0].click().run()
    _button(at, BACK_LABEL)[0].click().run()
    assert at.text_area[0].value == "Answer one."
    assert at.multiselect[0].value == ["Improve sleep", "Manage stress"]


def test_retake_prefills_from_saved_answers_and_round_trips():
    stored = {
        "improve": {"text": "stored text", "categories": ["Improve sleep"],
                    "focus": ["Improve sleep"]},
        "decrease": {"text": "", "categories": [], "focus": []},
        "long_term_goals": {"text": "", "categories": [], "focus": []},
        "distractions": {"text": "", "categories": [], "focus": []},
        "_priorities": {"top": ["Improve sleep"], "period": "1 week"},
    }
    at = _fresh(_seed_from=stored)
    assert at.text_area[0].value == "stored text"
    assert at.multiselect[0].value == ["Improve sleep"]

    for _ in range(5):                            # walk to the end, touch nothing
        nxt = _button(at, "Next")
        if not nxt:
            break
        nxt[0].click().run()
    assert at.radio[0].value == "1 week", "saved period was not restored"
    _button(at, "Save")[0].click().run()

    responses = _state(at, "_saved", [])[-1]["inquiry_responses"]
    assert responses["improve"] == stored["improve"]
    assert responses["_priorities"] == stored["_priorities"]


def test_write_matching_no_row_is_reported_as_failure():
    """An UPDATE filtered out by RLS is a 200 with an empty body, not an error."""
    at = _fresh(_db_matches=False)
    at.text_area[0].set_value("something").run()
    for _ in range(5):
        nxt = _button(at, "Next")
        if not nxt:
            break
        nxt[0].click().run()
    _button(at, "Save")[0].click().run()
    assert at.warning, "a write that stored nothing reported success"
    assert "could not be written" in at.warning[0].value


def test_completion_check_does_not_erase_the_answers_fallback():
    """The check is read-only: it must not stand in for the answers."""
    def script():
        import streamlit as st

        import insight_inquiry as inquiry

        class _Client:
            def table(self, name):
                return self

            def select(self, *a, **k):
                return self

            def eq(self, *a, **k):
                return self

            def limit(self, n):
                return self

            def execute(self):
                return type("R", (), {"data": [{"inquiry_completed_at": "2026-09-08"}]})

        st.session_state["_completed"] = inquiry.user_has_completed_inquiry(_Client(), "u1")

    at = AppTest.from_function(script, default_timeout=60)
    at.run()
    assert _state(at, "_completed") is True
    # Before the fix this check wrote `_STATE_KEY = {}`, so a later read
    # returned "no answers" instead of falling through to the real source.
    assert _state(at, iq._STATE_KEY, "absent") == "absent"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
