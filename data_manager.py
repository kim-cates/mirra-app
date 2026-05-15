"""Data management and database operations."""

import streamlit as st
from datetime import date, datetime, timedelta
from oura import user_today


def save_reflection(supabase, content: str, mood: float, keywords: list[str],
                    user_id: str, feelings: list[dict] | None = None):
    """Save a reflection entry to the database."""
    today = user_today().isoformat()
    supabase.table("reflections").upsert({
        "entry_date": today,
        "content": content,
        "mood": mood,
        "keywords": keywords,
        "feelings": feelings or [],
        "user_id": user_id,
        "updated_at": datetime.utcnow().isoformat(),
    }, on_conflict="user_id,entry_date").execute()


@st.cache_data(ttl=60)
def load_all_entries(supabase, user_id: str) -> list[dict]:
    """Load all reflection entries for a user."""
    res = supabase.table("reflections").select("*").eq("user_id", user_id).order("entry_date", desc=True).execute()
    return res.data or []


def load_stats(rows):
    """Calculate statistics from reflection rows."""
    total = len(rows)
    cutoff_30 = (user_today() - timedelta(days=30)).isoformat()
    recent = [r for r in rows if r["entry_date"] >= cutoff_30]
    avg_mood = round(sum(r["mood"] for r in recent) / len(recent), 1) if recent else 0.0
    cutoff_7 = (user_today() - timedelta(days=7)).isoformat()
    week_rows = [r for r in rows if r["entry_date"] >= cutoff_7]
    kw_count: dict[str, int] = {}
    for r in week_rows:
        for kw in (r.get("keywords") or []):
            kw_count[kw.lower()] = kw_count.get(kw.lower(), 0) + 1
    top_topic = max(kw_count, key=kw_count.get) if kw_count else "—"
    dated = sorted({r["entry_date"] for r in rows}, reverse=True)
    streak, check = 0, user_today()
    for d in dated:
        if d == check.isoformat():
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    today_rows = [r for r in rows if r["entry_date"] == user_today().isoformat()]
    return total, avg_mood, top_topic, streak, (today_rows[0] if today_rows else None)
