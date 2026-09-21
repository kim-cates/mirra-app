"""Tests for voice-to-text reflections (voice_input.py).

Runs standalone (``python3 tests/test_voice_input.py``) and under pytest.
Pure/offline — the Whisper API is stubbed at the requests level, no network,
no audio ever touches disk.
"""

import io
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_input  # noqa: E402
from voice_input import (  # noqa: E402
    VoiceTranscriptionError,
    audio_fingerprint,
    make_openai_transcriber,
    merge_transcript,
    resolve_transcriber,
)


# ── merge_transcript ─────────────────────────────────────────────────────────

def test_merge_into_empty_draft():
    assert merge_transcript("", "Slept badly.") == "Slept badly."


def test_merge_appends_with_blank_line():
    assert merge_transcript("Morning walk.", "Slept badly.") == \
        "Morning walk.\n\nSlept badly."


def test_merge_strips_whitespace():
    assert merge_transcript("Draft.  \n", "  spoken  ") == "Draft.\n\nspoken"


def test_merge_empty_transcript_keeps_draft():
    assert merge_transcript("Draft.", "   ") == "Draft."
    assert merge_transcript("", "") == ""


# ── audio_fingerprint ────────────────────────────────────────────────────────

def test_fingerprint_is_stable_and_distinguishes():
    a, b = b"take-one", b"take-two"
    assert audio_fingerprint(a) == audio_fingerprint(a)
    assert audio_fingerprint(a) != audio_fingerprint(b)


# ── resolve_transcriber ──────────────────────────────────────────────────────

def test_resolve_no_backend_returns_none():
    with mock.patch.object(voice_input, "_local_whisper_available",
                           return_value=False):
        assert resolve_transcriber({}) is None


def test_resolve_prefers_openai_key():
    t = resolve_transcriber({"OPENAI_API_KEY": "sk-test"})
    assert t is not None


def test_resolve_forced_off_wins_over_key():
    secrets = {"OPENAI_API_KEY": "sk-test", "VOICE_STT_BACKEND": "off"}
    assert resolve_transcriber(secrets) is None


def test_resolve_forced_openai_without_key_is_none():
    assert resolve_transcriber({"VOICE_STT_BACKEND": "openai"}) is None


def test_resolve_local_when_installed():
    with mock.patch.object(voice_input, "_local_whisper_available",
                           return_value=True):
        assert resolve_transcriber({}) is not None
        assert resolve_transcriber({"VOICE_STT_BACKEND": "local"}) is not None


# ── OpenAI backend (requests stubbed) ────────────────────────────────────────

def _resp(status=200, payload=None, text=""):
    return SimpleNamespace(status_code=status,
                           json=lambda: payload or {},
                           text=text or json.dumps(payload or {}))


def test_openai_transcriber_happy_path():
    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured.update(url=url, headers=headers, files=files, data=data)
        return _resp(payload={"text": "  I felt calm today. "})

    with mock.patch.object(voice_input.requests, "post", fake_post):
        t = make_openai_transcriber("sk-test")
        out = t(b"RIFFfake-wav-bytes", "audio/wav")

    assert out == "I felt calm today."
    assert captured["url"] == voice_input.OPENAI_TRANSCRIBE_URL
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["data"]["model"] == voice_input.OPENAI_STT_MODEL
    name, stream, mime = captured["files"]["file"]
    assert name.endswith(".wav") and mime == "audio/wav"
    # Audio is passed as an in-memory stream — nothing ever hits disk.
    assert isinstance(stream, io.BytesIO)


def test_openai_transcriber_http_error_raises():
    with mock.patch.object(voice_input.requests, "post",
                           lambda *a, **k: _resp(status=401, text="bad key")):
        t = make_openai_transcriber("sk-bad")
        try:
            t(b"bytes", "audio/wav")
            assert False, "expected VoiceTranscriptionError"
        except VoiceTranscriptionError as e:
            assert "401" in str(e)


def test_openai_transcriber_network_error_raises():
    def boom(*a, **k):
        raise voice_input.requests.ConnectionError("no route")

    with mock.patch.object(voice_input.requests, "post", boom):
        t = make_openai_transcriber("sk-test")
        try:
            t(b"bytes", "audio/wav")
            assert False, "expected VoiceTranscriptionError"
        except VoiceTranscriptionError:
            pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
