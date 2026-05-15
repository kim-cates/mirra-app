# Mirra × Oura Integration Guide

Drop-in instructions for wiring Oura into your existing `app.py`.
Five edits total. None touch your core reflection logic.

---

## 0. Prerequisites

**Run the migration.** Open Supabase → SQL Editor → paste `migrations.sql` → run.
You should see two new tables: `oura_daily` and `oura_credentials`.

**Add to `.streamlit/secrets.toml`** (only the OAuth keys are required if you
want OAuth; PAT works without any secrets):

```toml
# Existing
SUPABASE_URL = "..."
SUPABASE_KEY = "..."
ANTHROPIC_API_KEY = "..."

# New — OAuth only (skip if PAT-only)
OURA_CLIENT_ID = "your_client_id_from_ouraring.com"
OURA_CLIENT_SECRET = "your_client_secret"
OURA_REDIRECT_URI = "http://localhost:8501"   # or your deployed URL, exact match
```

To get OAuth credentials, register an app at
<https://cloud.ouraring.com/oauth/applications>. The redirect URI must match
exactly between the Oura dashboard and your secrets file.

**Drop both Python files next to `app.py`:**
- `oura.py`
- `oura_ui.py`

---

## 1. Imports (top of `app.py`, near the others)

```python
import oura
import oura_ui
```

---

## 2. Handle OAuth callback (right after login is confirmed)

In your auth flow, after you've set `st.session_state["user_id"]` and confirmed
the user is logged in, but BEFORE rendering tabs, add:

```python
oura_ui.handle_oauth_callback(supabase, st.session_state["user_id"])
```

This is a no-op if there's no `?code=...` in the URL. It only runs work when
the user is returning from Oura's authorization page.

---

## 3. Load Oura data alongside reflections

Wherever you currently do `rows = load_all_entries(user_id)` (just before
the tabs render), add a sibling call:

```python
rows = load_all_entries(st.session_state["user_id"])
oura_by_date = oura.load_oura_for_user(supabase, st.session_state["user_id"])
```

You can also wrap that in `@st.cache_data(ttl=60)` like your existing loader
if you want — the function is already cheap, but consistency is fine:

```python
@st.cache_data(ttl=60)
def load_oura_cached(user_id: str) -> dict:
    return oura.load_oura_for_user(supabase, user_id)
```

---

## 4. Add a Settings tab

Find your tab definitions (something like
`tab1, tab2, tab3 = st.tabs([...])`) and add Settings:

```python
# Before
tab_today, tab_history, tab_topics = st.tabs(["Today", "History", "Topics"])

# After
tab_today, tab_history, tab_topics, tab_settings = st.tabs(
    ["Today", "History", "Topics", "Settings"]
)

with tab_today:
    render_today_tab(rows, oura_by_date)   # <-- now passes oura data

with tab_history:
    render_history_tab(rows, oura_by_date)  # <-- if you want chart here

with tab_topics:
    render_bertopic_tab(rows)

with tab_settings:
    oura_ui.render_settings_tab(supabase, st.session_state["user_id"])
```

---

## 5. Show Oura badges on the Today tab

In `render_today_tab`, change the signature and add the badge call right
under the streak header (around line 1420 in your current code):

```python
def render_today_tab(rows, oura_by_date):
    total, avg_mood_30d, top_topic, streak, today_row = load_stats(rows)
    # ... existing code ...

    col_title, col_streak = st.columns([3, 1])
    with col_title:
        st.markdown(f'<div class="date-label">{today_str}</div>', unsafe_allow_html=True)
        st.markdown('<p class="title-text">Today\'s reflection</p>', unsafe_allow_html=True)
    with col_streak:
        st.markdown(f'<div style="text-align:right;padding-top:4px"><span class="streak-badge">{streak_lbl}</span></div>', unsafe_allow_html=True)

    # ── NEW: Oura badges ──────────────────────────────────────────
    oura_today = oura_by_date.get(date.today().isoformat())
    oura_ui.render_oura_badges(oura_today)
    # ──────────────────────────────────────────────────────────────

    st.markdown('<div class="section-label">What\'s on your mind?</div>',
                unsafe_allow_html=True)
    # ... rest of existing code ...
```

---

## 6. Add the Mood vs Sleep chart

Pick a tab to host it — I'd recommend your Analytics / History tab, right
near the existing mood distribution chart. Wherever feels right, add:

```python
oura_ui.render_mood_sleep_chart(rows, oura_by_date)
```

That's it. Self-contained. Renders nothing useful until the user has both
reflections and Oura days that overlap, then shows a scatter + trendline +
Pearson r + interpretation.

---

## 7. (Optional) Send Oura context to Claude

Wherever you call `ai_client.messages.create(...)` for AI insights, build a
richer prompt:

```python
oura_today = oura_by_date.get(date.today().isoformat(), {})

context_lines = [f"Reflection: {content}", f"Mood: {mood}/10"]
if oura_today.get("sleep_score") is not None:
    context_lines.append(f"Sleep score: {oura_today['sleep_score']}")
if oura_today.get("readiness_score") is not None:
    context_lines.append(f"Readiness: {oura_today['readiness_score']}")
if oura_today.get("hrv_avg") is not None:
    context_lines.append(f"HRV: {oura_today['hrv_avg']} ms")

prompt = "\n".join(context_lines)
# pass `prompt` into your existing Anthropic call
```

This is where the integration starts paying off — Claude can spot
"you write about anxiety on low-HRV days" patterns you'd miss otherwise.

---

## Testing checklist

1. ✅ Run migration. Confirm tables in Supabase.
2. ✅ Add files, restart Streamlit.
3. ✅ Open app, log in. Go to Settings tab.
4. ✅ Connect with PAT (fastest path to validation).
5. ✅ Confirm "Backfilling 30 days…" runs, then `oura_daily` has rows.
6. ✅ Go to Today tab → badges should show today's scores (or "no data yet"
   if it's still early morning).
7. ✅ Visit your analytics tab → mood vs sleep chart renders.
8. ✅ Try the OAuth flow once your redirect URI is registered.

---

## Gotchas

- **Oura morning lag.** Daily summaries land mid-morning after wake. Don't
  expect data for "today" before ~9 AM.
- **Rate limit: 5000 req/day per token.** The 60-second cache + range
  fetches keep you well under, but don't poll on every page load.
- **PAT = no expiry; OAuth = 24h access tokens.** `get_valid_token()`
  handles the refresh automatically — but only if `OURA_CLIENT_ID/SECRET`
  are in secrets.
- **Redirect URI must match exactly** between Oura dashboard and
  `OURA_REDIRECT_URI` (including http vs https, trailing slash, port).
- **RLS is on.** If you see empty results, double-check the user is
  authenticated and Supabase is using the user's JWT, not the anon key
  with no session.
