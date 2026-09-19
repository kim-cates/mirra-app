"""Voice-to-text input for the daily reflection (isolated module).

Задача с созвона с Ким 07.09: дать надиктовать рефлексию вместо набора
текста — "so they don't have to type it out". Транскрипт ложится обычным
текстом в поле рефлексии и дальше живёт как всегда (`reflections.content`,
`nlp_utils` / `insights` ничего не знают про голос).

Privacy (HIPAA-планка из CLAUDE.md): аудио живёт только в памяти процесса —
записали, транскрибировали, выбросили. Ничего не пишется на диск и не
сохраняется в БД; в Supabase уходит только итоговый текст, который
пользователь видит и может отредактировать перед сохранением.

STT-бэкенды подключаемые; выбор продакшн-бэкенда (облако vs локальный) —
решение Ким, не наше:

- ``openai``  — Whisper API (нужен ``OPENAI_API_KEY`` в secrets). Аудио
                уходит третьей стороне — перед включением в прод сверить
                с privacy policy.
- ``local``   — faster-whisper, если пакет установлен. Аудио не покидает
                сервер; бесплатно, но грузит CPU.
- нет бэкенда — модуль ничего не рисует, приложение выглядит как раньше.

``VOICE_STT_BACKEND`` в secrets форсирует выбор ("openai" / "local" /
"off"); без него берётся первый доступный в порядке выше.
"""
from __future__ import annotations

import hashlib
import io
from typing import Callable, Mapping, Optional

import requests

# Whisper авто-детектит язык (у Ким EN, у Игоря RU) — язык не фиксируем.
# Если авто-детект будет промахиваться на коротких записях, поле в профиле
# пользователя — следующий шаг (см. docs/handoff/voice-to-text.md).

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_STT_MODEL = "whisper-1"
LOCAL_WHISPER_MODEL = "base"  # ~74 MB, скачивается при первом использовании

# Transcriber: (audio_bytes, mime_type) -> text
Transcriber = Callable[[bytes, str], str]


class VoiceTranscriptionError(Exception):
    """STT backend failed; the recording stays un-transcribed."""


# ── Backends ─────────────────────────────────────────────────────────────────

def make_openai_transcriber(api_key: str) -> Transcriber:
    """Whisper API over plain requests (no openai package needed)."""
    def transcribe(audio: bytes, mime: str) -> str:
        ext = (mime.split("/")[-1] or "wav").split(";")[0]
        try:
            resp = requests.post(
                OPENAI_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (f"reflection.{ext}", io.BytesIO(audio), mime)},
                data={"model": OPENAI_STT_MODEL},
                timeout=60,
            )
        except requests.RequestException as e:
            raise VoiceTranscriptionError(f"Whisper API unreachable: {e}") from e
        if resp.status_code != 200:
            raise VoiceTranscriptionError(
                f"Whisper API error {resp.status_code}: {resp.text[:200]}")
        return (resp.json().get("text") or "").strip()
    return transcribe


def make_local_transcriber(model_name: str = LOCAL_WHISPER_MODEL) -> Transcriber:
    """faster-whisper, lazy: модель грузится при первой транскрипции."""
    state: dict = {}

    def transcribe(audio: bytes, mime: str) -> str:
        if "model" not in state:
            from faster_whisper import WhisperModel  # optional dependency
            state["model"] = WhisperModel(model_name, compute_type="int8")
        segments, _info = state["model"].transcribe(io.BytesIO(audio))
        return " ".join(seg.text.strip() for seg in segments).strip()
    return transcribe


def _local_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def resolve_transcriber(secrets: Mapping) -> Optional[Transcriber]:
    """Pick an STT backend from secrets/installed packages, or None."""
    forced = str(secrets.get("VOICE_STT_BACKEND", "")).strip().lower()
    if forced == "off":
        return None
    if forced == "openai" or (not forced and secrets.get("OPENAI_API_KEY")):
        key = secrets.get("OPENAI_API_KEY")
        return make_openai_transcriber(key) if key else None
    if forced == "local" or (not forced and _local_whisper_available()):
        return make_local_transcriber() if _local_whisper_available() else None
    return None


# ── Pure helpers (tested in tests/test_voice_input.py) ───────────────────────

def merge_transcript(existing: str, transcript: str) -> str:
    """Append a new transcript to the current draft, keeping it editable text."""
    transcript = (transcript or "").strip()
    existing = (existing or "").rstrip()
    if not transcript:
        return existing
    if not existing:
        return transcript
    return f"{existing}\n\n{transcript}"


def audio_fingerprint(audio: bytes) -> str:
    """Stable id of a recording so reruns don't re-transcribe the same take."""
    return hashlib.sha256(audio).hexdigest()


# ── Streamlit UI ─────────────────────────────────────────────────────────────

def render_voice_input(transcriber: Optional[Transcriber],
                       key: str = "voice_reflection") -> Optional[str]:
    """Mic widget; returns a NEW transcript once per recording, else None.

    Call this BEFORE the text_area is instantiated in the same run — the
    caller merges the transcript into the text_area's session_state key,
    which Streamlit only allows before the widget exists.
    """
    import streamlit as st

    if transcriber is None:
        return None  # backend not chosen yet — app looks unchanged

    audio = st.audio_input(
        "Or record it — your words land in the box above as text",
        key=f"{key}_audio",
    )
    st.caption("Audio is transcribed in memory and never stored — "
               "only the text you save.")
    if audio is None:
        return None

    data = audio.getvalue()
    fp = audio_fingerprint(data)
    if st.session_state.get(f"{key}_last_fp") == fp:
        return None  # same take on a rerun — already transcribed

    try:
        with st.spinner("Transcribing…"):
            text = transcriber(data, audio.type or "audio/wav")
    except VoiceTranscriptionError as e:
        st.warning(f"Couldn't transcribe that recording — try again. ({e})")
        return None

    st.session_state[f"{key}_last_fp"] = fp
    return text or None
