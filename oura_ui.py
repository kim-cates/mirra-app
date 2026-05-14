"""
UI components for Oura integration in Mirra.

Exposes:
  - render_settings_tab(supabase, user_id)         → connect / sync / disconnect
  - render_oura_badges(oura_today)                 → small cards on Today tab
  - render_mood_vs_biometric_chart(rows, oura_by_date)  → analytics chart
  - handle_oauth_callback(supabase, user_id)       → call once at top of app
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import oura


# ── OAuth callback handling ───────────────────────────────────────────────────
def handle_oauth_callback(supabase, user_id: str) -> None:
    """
    Call this once near the top of the app, AFTER user is logged in.

    If the URL contains ?code=... and ?state=... and the state matches the one
    we stashed in session, exchange the code for tokens and persist them.
    """
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    if not code or not state:
        return

    expected = st.session_state.get("oura_oauth_state")
    if not expected or state != expected:
        st.error("Oura OAuth state mismatch — please retry the connection.")
        st.query_params.clear()
        return

    try:
        client_id = st.secrets["OURA_CLIENT_ID"]
        client_secret = st.secrets["OURA_CLIENT_SECRET"]
        redirect_uri = st.secrets["OURA_REDIRECT_URI"]
    except KeyError as e:
        st.error(f"Missing Oura OAuth secret: {e}. Add to .streamlit/secrets.toml")
        return

    try:
        token_payload = oura.exchange_code_for_token(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        oura.save_oauth_credentials(supabase, user_id, token_payload)

        # Initial backfill
        with st.spinner("Connected! Backfilling 30 days of Oura data…"):
            oura.sync_oura(supabase, user_id, token_payload["access_token"], days_back=30)

        st.success("Oura connected ✓")
    except oura.OuraError as e:
        st.error(f"Oura connection failed: {e}")
    finally:
        # Clear the URL params and the state nonce so we don't re-process
        st.query_params.clear()
        st.session_state.pop("oura_oauth_state", None)


# ── Settings tab ──────────────────────────────────────────────────────────────
def render_settings_tab(supabase, user_id: str) -> None:
    st.markdown('<p class="title-text">Settings</p>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#888; font-size:0.92rem; margin-bottom:1.2rem">'
        'Connect external data sources to enrich your reflections.'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">Oura Ring</div>', unsafe_allow_html=True)

    # Check existing connection
    res = supabase.table("oura_credentials").select("*").eq("user_id", user_id).execute()
    creds = (res.data or [None])[0]

    if creds:
        _render_connected_state(supabase, user_id, creds)
    else:
        _render_disconnected_state(supabase, user_id)


def _render_connected_state(supabase, user_id: str, creds: dict) -> None:
    auth_label = "Personal Access Token" if creds["auth_type"] == "pat" else "OAuth"
    connected_date = (creds.get("connected_at") or "")[:10]

    st.markdown(
        f'<div class="save-msg">✓ Oura connected via {auth_label}'
        f'{" since " + connected_date if connected_date else ""}.</div>',
        unsafe_allow_html=True,
    )

    # Quick stats: how many days of data we have
    count_res = supabase.table("oura_daily").select("entry_date", count="exact") \
        .eq("user_id", user_id).execute()
    n_days = count_res.count if hasattr(count_res, "count") else len(count_res.data or [])

    st.markdown(
        f'<div style="color:#888; font-size:0.9rem; margin:0.6rem 0 1rem">'
        f'{n_days} days of Oura data stored.'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_sync_7, col_sync_30, col_disconnect = st.columns([1, 1, 1])

    with col_sync_7:
        if st.button("Sync last 7 days", use_container_width=True):
            _do_sync(supabase, user_id, creds, days_back=7)

    with col_sync_30:
        if st.button("Sync last 30 days", use_container_width=True):
            _do_sync(supabase, user_id, creds, days_back=30)

    with col_disconnect:
        if st.button("Disconnect", use_container_width=True):
            oura.disconnect(supabase, user_id)
            st.cache_data.clear()
            st.rerun()


def _do_sync(supabase, user_id: str, creds: dict, days_back: int) -> None:
    try:
        # For OAuth, this auto-refreshes if needed
        client_id = st.secrets.get("OURA_CLIENT_ID") if creds["auth_type"] == "oauth" else None
        client_secret = st.secrets.get("OURA_CLIENT_SECRET") if creds["auth_type"] == "oauth" else None
        token = oura.get_valid_token(supabase, user_id, client_id, client_secret)
        if not token:
            st.error("No valid token found.")
            return

        with st.spinner(f"Syncing {days_back} days from Oura…"):
            n = oura.sync_oura(supabase, user_id, token, days_back=days_back)
        st.success(f"Synced {n} day(s) ✓")
        st.cache_data.clear()
    except oura.OuraAuthError:
        st.error("Oura token is no longer valid. Please disconnect and reconnect.")
    except oura.OuraRateLimitError:
        st.warning("Oura rate limit hit. Try again in a few minutes.")
    except oura.OuraError as e:
        st.error(f"Sync failed: {e}")


def _render_disconnected_state(supabase, user_id: str) -> None:
    pat_tab, oauth_tab = st.tabs(["Personal Access Token", "OAuth (recommended for shared use)"])

    # ─── PAT flow ───
    with pat_tab:
        st.markdown(
            'Generate a Personal Access Token at '
            '[cloud.ouraring.com/personal-access-tokens]'
            '(https://cloud.ouraring.com/personal-access-tokens), then paste below.'
        )
        token = st.text_input("Oura Personal Access Token", type="password",
                              key="oura_pat_input")
        if st.button("Connect with PAT", type="primary", key="oura_pat_connect"):
            if not token:
                st.warning("Paste your token first.")
                return
            try:
                with st.spinner("Validating token…"):
                    info = oura.validate_token(token)
                oura.save_pat_credentials(supabase, user_id, token)
                with st.spinner("Backfilling 30 days of Oura data…"):
                    oura.sync_oura(supabase, user_id, token, days_back=30)
                st.success(f"Connected ✓ (Oura user: {info.get('email', 'unknown')})")
                st.cache_data.clear()
                st.rerun()
            except oura.OuraAuthError as e:
                st.error(f"Token rejected: {e}")
            except oura.OuraError as e:
                st.error(f"Connection failed: {e}")

    # ─── OAuth flow ───
    with oauth_tab:
        try:
            client_id = st.secrets["OURA_CLIENT_ID"]
            redirect_uri = st.secrets["OURA_REDIRECT_URI"]
        except KeyError:
            st.info(
                "OAuth not configured yet. Add `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`, "
                "and `OURA_REDIRECT_URI` to `.streamlit/secrets.toml`. "
                "Register your app at [cloud.ouraring.com/oauth/applications]"
                "(https://cloud.ouraring.com/oauth/applications)."
            )
            return

        st.markdown(
            "Click below to authorize Mirra to read your Oura data. "
            "You'll be redirected back here when done."
        )

        # Generate fresh state nonce per click and stash in session
        if st.button("Connect with Oura", type="primary", key="oura_oauth_connect"):
            state = secrets.token_urlsafe(24)
            st.session_state["oura_oauth_state"] = state
            url = oura.build_oauth_authorize_url(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=state,
            )
            # Streamlit can't redirect natively, so render a link the user clicks.
            st.markdown(
                f'<a href="{url}" target="_self" '
                f'style="display:inline-block;margin-top:0.6rem;padding:0.6rem 1.2rem;'
                f'background:#3dab7a;color:white;border-radius:8px;'
                f'text-decoration:none;font-weight:600">Authorize on Oura →</a>',
                unsafe_allow_html=True,
            )


# ── Today-tab badges ──────────────────────────────────────────────────────────
def render_oura_badges(oura_today: dict | None) -> None:
    """
    Render a horizontal strip of small cards showing today's Oura metrics.
    Pass the merged view from oura.build_today_view(), or None if no data exists
    for either today or yesterday.
    """
    if not oura_today:
        st.markdown(
            '<div style="color:#bbb; font-size:0.88rem; margin:0.6rem 0 1rem">'
            'No Oura data yet — connect in Settings or wait for your first sync.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    sleep = oura_today.get("sleep_score")
    readiness = oura_today.get("readiness_score")
    activity = oura_today.get("activity_score")
    total_sleep = oura_today.get("total_sleep_seconds")
    resting_hr = oura_today.get("resting_hr")
    sources = oura_today.get("_source_by_metric", {})

    # Only show duration alongside the score when they came from the SAME night.
    # `total_sleep_seconds` and `sleep_score` are fetched independently and can
    # post at different times, so without this check a freshly-synced score from
    # today can end up labelled with yesterday's duration (4h49m under today's
    # 87, etc.) — which looks like a stale render and confuses users.
    sleep_source = sources.get("sleep_score")
    total_sleep_source = sources.get("total_sleep_seconds")
    if total_sleep and sleep_source == total_sleep_source:
        sleep_hours = f"{total_sleep // 3600}h {(total_sleep % 3600) // 60}m"
    else:
        sleep_hours = None  # let _sublabel decide today/yesterday/—

    def _fmt(v):
        return str(int(v)) if v is not None else "—"

    def _color(score):
        if score is None:
            return "#999"
        if score >= 85:
            return "#3dab7a"
        if score >= 70:
            return "#d4850a"
        return "#e05a3a"

    def _sublabel(metric: str, value, default: str) -> str:
        """Show 'yesterday' tag when value comes from yesterday, else default.

        When value is missing entirely, show 'not synced yet' for sleep-derived
        metrics (which post in the morning) instead of an empty dash, so users
        understand the data is on its way rather than thinking the app is broken.
        """
        if value is None:
            if metric in ("sleep_score", "readiness_score", "resting_hr"):
                return "not synced yet"
            return "—"
        if sources.get(metric) == "yesterday":
            return "yesterday"
        return default

    def _card(label: str, value_str: str, sublabel_str: str, accent: str) -> str:
        # Modern card: white background, hairline border, small colored accent dot
        # next to the label rather than a heavy left bar.
        return f"""
      <div style="background:white; border:1px solid #ece9df; border-radius:12px;
                  padding:0.85rem 1rem 0.9rem;">
        <div style="display:flex; align-items:center; gap:7px; margin-bottom:6px;">
          <span style="display:inline-block; width:6px; height:6px; border-radius:999px;
                       background:{accent};"></span>
          <span style="font-size:0.66rem; font-weight:600; color:#999;
                       letter-spacing:0.14em; text-transform:uppercase;">{label}</span>
        </div>
        <div style="font-family:'Lora',serif; font-size:1.6rem; font-weight:600;
                    color:#1a1a1a; line-height:1.05; letter-spacing:-0.01em;">{value_str}</div>
        <div style="font-size:0.78rem; color:#aaa; margin-top:4px">{sublabel_str}</div>
      </div>"""

    html = f"""
    <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; margin:0.4rem 0 1.2rem">
      {_card('Sleep',      _fmt(sleep),      _sublabel('sleep_score',     sleep,      sleep_hours or 'today'), _color(sleep))}
      {_card('Readiness',  _fmt(readiness),  _sublabel('readiness_score', readiness,  'today'),                _color(readiness))}
      {_card('Activity',   _fmt(activity),   _sublabel('activity_score',  activity,   'today'),                _color(activity))}
      {_card('Resting HR', _fmt(resting_hr), _sublabel('resting_hr',      resting_hr, 'bpm'),                  '#5b6fa6')}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ── Mood vs biometric scatter ────────────────────────────────────────────────
# Available x-axis metrics, in the order they appear in the dropdown. Each
# entry: (display label, oura field, unit, lower_is_better).
# `lower_is_better=True` flips the interpretation copy — for resting HR, a
# positive correlation with mood would mean "worse mood on lower-stress days,"
# i.e. an unfavorable pattern.
_MOOD_VS_METRICS = [
    ("Sleep score",   "sleep_score",     "",      False),
    ("Readiness",     "readiness_score", "",      False),
    ("HRV",           "hrv_avg",         "ms",    False),
    ("Resting HR",    "resting_hr",      "bpm",   True),
    ("REM sleep",     "rem_sleep_min",   "min",   False),
]


def render_mood_vs_biometric_chart(reflection_rows: list[dict],
                                   oura_by_date: dict[str, dict]) -> None:
    """
    Scatter plot of mood (y) against a user-selected biometric (x), one point
    per day where both exist. Trendline + correlation + plain-English read
    added once there are enough matched days.
    """
    # ── Metric picker ────────────────────────────────────────────────────────
    label_to_spec = {label: (field, unit, lib) for label, field, unit, lib in _MOOD_VS_METRICS}
    header_col, picker_col = st.columns([3, 2])
    with header_col:
        st.markdown('<div class="section-label">Mood vs biometric</div>', unsafe_allow_html=True)
    with picker_col:
        metric_label = st.selectbox(
            "Compare mood against",
            options=list(label_to_spec.keys()),
            index=0,
            key="mood_vs_metric",
            label_visibility="collapsed",
        )
    field, unit, lower_is_better = label_to_spec[metric_label]

    # ── Join reflection rows with Oura on entry_date, picking the selected
    # metric for the x-axis. Skip days where either side is missing.
    points = []
    for r in reflection_rows:
        d = r["entry_date"]
        oura_row = oura_by_date.get(d)
        if not oura_row:
            continue
        x_val = oura_row.get(field)
        if x_val is None:
            continue
        points.append({
            "date": d,
            "mood": float(r["mood"]),
            "x": float(x_val),
            # Keep a couple of secondary metrics in hover for context.
            "sleep_score": oura_row.get("sleep_score"),
            "readiness": oura_row.get("readiness_score"),
        })

    if len(points) < 3:
        st.markdown(
            f'<div class="min-data-msg">Need at least 3 days with both a reflection '
            f'and {metric_label.lower()} data to plot. Keep journaling.</div>',
            unsafe_allow_html=True,
        )
        return

    x_vals    = [p["x"] for p in points]
    mood_vals = [p["mood"] for p in points]
    dates     = [p["date"] for p in points]

    x_unit_suffix = f" {unit}" if unit else ""
    hover = []
    for p in points:
        bits = [f"<b>{p['date']}</b>", f"Mood: {p['mood']}", f"{metric_label}: {int(p['x'])}{x_unit_suffix}"]
        # Tuck in the other metric for context where available (skip if the
        # selected metric already covers it).
        if field != "sleep_score" and p.get("sleep_score") is not None:
            bits.append(f"Sleep: {int(p['sleep_score'])}")
        if field != "readiness_score" and p.get("readiness") is not None:
            bits.append(f"Readiness: {int(p['readiness'])}")
        hover.append("<br>".join(bits))

    fig = go.Figure()

    # Scatter points — colored by mood so the eye reads vertical position twice.
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=mood_vals,
        mode="markers",
        marker=dict(
            size=10,
            color=mood_vals,
            colorscale=[[0, "#e05a3a"], [0.5, "#d4850a"], [1, "#3dab7a"]],
            cmin=1, cmax=10,
            line=dict(width=1, color="white"),
        ),
        text=hover,
        hoverinfo="text",
        showlegend=False,
    ))

    # Linear trendline if enough points
    if len(points) >= 5:
        coeffs = np.polyfit(x_vals, mood_vals, 1)
        x_line = np.linspace(min(x_vals), max(x_vals), 50)
        y_line = np.polyval(coeffs, x_line)
        fig.add_trace(go.Scatter(
            x=x_line, y=y_line,
            mode="lines",
            line=dict(color="#5b6fa6", width=2, dash="dash"),
            name="Trend",
            hoverinfo="skip",
            showlegend=False,
        ))
        corr = float(np.corrcoef(x_vals, mood_vals)[0, 1])
        corr_label = f"r = {corr:+.2f}"
    else:
        corr = None
        corr_label = ""

    x_axis_title = f"{metric_label}{x_unit_suffix}".strip()
    fig.update_layout(
        paper_bgcolor="#f7f6f2",
        plot_bgcolor="#f7f6f2",
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis=dict(title=x_axis_title, showgrid=True, gridcolor="#e5e5e0",
                   zeroline=False, color="#2a2a2a"),
        yaxis=dict(title="Mood (1–10)", showgrid=True, gridcolor="#e5e5e0",
                   zeroline=False, color="#2a2a2a", range=[0.5, 10.5]),
        font=dict(family="DM Sans"),
        height=380,
        title=dict(
            text=f"<span style='color:#888;font-size:0.9rem'>{len(points)} matched days &nbsp;&middot;&nbsp; {corr_label}</span>",
            x=0.02, xanchor="left",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Plain-English interpretation ────────────────────────────────────────
    # For lower-is-better metrics (resting HR), invert the sign of r when
    # picking copy so a NEGATIVE correlation reads as the favorable pattern
    # ("lower RHR days have higher mood"). The label stays neutral about
    # direction otherwise — we just describe what's there.
    if corr is None:
        return
    metric_lower = metric_label.lower()
    effective = -corr if lower_is_better else corr
    if effective >= 0.4:
        interpretation = (
            f"Your mood tends to track {metric_lower} meaningfully — "
            f"{'lower' if lower_is_better else 'better'} {metric_lower}, better days."
        )
        tone = "#3dab7a"
    elif effective >= 0.15:
        interpretation = f"There's a mild positive link between {metric_lower} and mood here."
        tone = "#d4850a"
    elif effective <= -0.15:
        # The opposite direction from what you'd typically expect.
        direction_phrase = (
            f"higher {metric_lower}" if lower_is_better else f"lower {metric_lower}"
        )
        interpretation = (
            f"Surprisingly, {direction_phrase} correlates with higher mood in your data — "
            f"worth digging into."
        )
        tone = "#e05a3a"
    else:
        interpretation = (
            f"No clear {metric_lower}-mood pattern yet — your mood may be driven by other factors."
        )
        tone = "#888"
    st.markdown(
        f'<div style="background:#f0efe8; border-left:4px solid {tone};'
        f'border-radius:8px; padding:0.7rem 1rem; margin-top:0.4rem;'
        f'color:#2a2a2a; font-size:0.92rem">{interpretation}</div>',
        unsafe_allow_html=True,
    )