"""
Voice-to-text · Standalone demo — try record → transcribe → text-in-the-box
without a Mirra login, without Supabase, and (if no STT backend is set up)
without any external service.

    streamlit run demo_voice_app.py --server.port 8502

Why a separate entry point: `app.py` needs a Mirra login and loads the whole
NLP stack. This page renders the *same* `voice_input` code the daily
reflection tab uses, wired to a plain text box instead of the real form.

Backend pick-up is the real one (`resolve_transcriber(st.secrets)`):
    OPENAI_API_KEY in secrets      → Whisper API
    faster-whisper installed       → local Whisper
    neither                        → canned transcript (clearly labeled), so
                                     the record→box UX is still demoable.

Nothing is written to disk or any database — the recording lives in memory
and dies with the rerun. The STT backend for production is Kim's call.
"""
from __future__ import annotations

import streamlit as st

from voice_input import merge_transcript, render_voice_input, resolve_transcriber

st.set_page_config(page_title="Mirra · voice demo", layout="centered")
st.title("Voice-to-text reflection — demo")

transcriber = resolve_transcriber(st.secrets)
if transcriber is None:
    st.info("No STT backend configured (no OPENAI_API_KEY, no faster-whisper) — "
            "using a **canned transcript** so you can still feel the flow. "
            "The recording itself is real; only the words are fake.")

    def transcriber(audio: bytes, mime: str) -> str:  # noqa: F811
        secs = max(1, len(audio) // 32000)  # ~16-bit 16 kHz mono guess
        return (f"[canned transcript of your ~{secs}s recording — a real "
                f"backend would put your words here]")
else:
    st.caption("Real STT backend active.")

if "demo_reflection" not in st.session_state:
    st.session_state["demo_reflection"] = ""

st.markdown("**What's on your mind?**")
text_slot = st.container()
new_text = render_voice_input(transcriber, key="demo_voice")
if new_text:
    st.session_state["demo_reflection"] = merge_transcript(
        st.session_state["demo_reflection"], new_text)
with text_slot:
    st.text_area("reflection", key="demo_reflection", height=140,
                 label_visibility="collapsed",
                 placeholder="Speak below, or type here — both land in this box.")

st.divider()
st.caption("This box is exactly what would be saved to `reflections.content` "
           "on the real page — edit it first if the transcript needs fixing.")
