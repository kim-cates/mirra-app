"""Tests for Oura full-history sync and pagination.

Runs standalone (``python tests/test_oura_history.py``) and under pytest, in the
style of the other tests here. No network: ``oura.requests`` is swapped for a
fake that serves canned pages.

The pagination tests are the important ones. Oura returns one page plus a
``next_token``, and the old single-call fetch ignored it — so any range larger
than a page came back short with no error at all. A 7- or 30-day sync never
reached that limit, which is why it was invisible; a full-history sync would
have silently dropped most of the record.
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oura  # noqa: E402


# ── Fakes ────────────────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeOura:
    """Serves `pages[endpoint]` as a next_token chain, recording every call.

    With `window_mode=True` it ignores `pages` and instead answers every request
    with one record dated at the window's start_date — the way to exercise a
    multi-window sync that actually returns data in each window.
    """

    def __init__(self, pages, fail_on_call=None, status=429, window_mode=False):
        self.pages = pages
        self.calls = []
        self.fail_on_call = fail_on_call
        self.status = status
        self.window_mode = window_mode

    def get(self, url, headers=None, params=None, timeout=None):
        endpoint = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append((endpoint, dict(params or {})))
        if self.fail_on_call is not None and len(self.calls) > self.fail_on_call:
            return FakeResponse({"detail": "slow down"}, status_code=self.status)

        if self.window_mode:
            start = (params or {}).get("start_date")
            if endpoint == "sleep":
                return FakeResponse({"data": [_sleep_period(start)]})
            return FakeResponse({"data": [_day(start)]})

        chain = self.pages.get(endpoint, [{"data": []}])
        index = int((params or {}).get("next_token") or 0)
        page = chain[index] if index < len(chain) else {"data": []}
        out = {"data": page.get("data", [])}
        if index + 1 < len(chain):
            out["next_token"] = str(index + 1)
        return FakeResponse(out)


class FakeSupabase:
    """Records each upsert batch so we can see what was written and when."""

    def __init__(self):
        self.batches = []

    def table(self, name):
        self.last_table = name
        return self

    def upsert(self, rows, on_conflict=None):
        self._pending = rows
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        pending = getattr(self, "_pending", None)
        if pending is not None:
            self.batches.append(list(pending))
            self._pending = None
        return type("R", (), {"data": []})

    @property
    def rows(self):
        return [row for batch in self.batches for row in batch]


def _day(day: str, score: int = 80):
    return {"day": day, "score": score}


def _sleep_period(day: str, seconds: int = 27000):
    return {
        "day": day,
        "bedtime_end": f"{day}T14:30:00+00:00",   # 04:30 HST — same local day
        "total_sleep_duration": seconds,
        "average_hrv": 55,
        "lowest_heart_rate": 52,
        "deep_sleep_duration": 4800,
        "rem_sleep_duration": 5400,
        "type": "long_sleep",
    }


def _install(monkey_pages, **kwargs):
    fake = FakeOura(monkey_pages, **kwargs)
    oura.requests = fake
    return fake


def _restore():
    import requests
    oura.requests = requests


# ── Pagination ───────────────────────────────────────────────────────────────
def test_get_all_follows_next_token():
    fake = _install({"daily_sleep": [
        {"data": [_day("2026-01-01"), _day("2026-01-02")]},
        {"data": [_day("2026-01-03")]},
    ]})
    try:
        items = oura._get_all("daily_sleep", "tok", {"start_date": "2026-01-01"})
    finally:
        _restore()
    assert [i["day"] for i in items] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert len(fake.calls) == 2, fake.calls


def test_get_all_carries_the_original_params_across_pages():
    """A dropped start_date on page 2 would quietly widen the query."""
    fake = _install({"daily_sleep": [
        {"data": [_day("2026-01-01")]},
        {"data": [_day("2026-01-02")]},
    ]})
    try:
        oura._get_all("daily_sleep", "tok",
                      {"start_date": "2026-01-01", "end_date": "2026-01-31"})
    finally:
        _restore()
    for _, params in fake.calls:
        assert params["start_date"] == "2026-01-01"
        assert params["end_date"] == "2026-01-31"


def test_get_all_raises_rather_than_truncating():
    """Endless pagination must fail loudly, not return a partial history."""
    endless = [{"data": [_day(f"2026-01-{i + 1:02d}")]} for i in range(10)]
    _install({"daily_sleep": endless})
    try:
        oura._get_all("daily_sleep", "tok", {}, max_pages=3)
    except oura.OuraError as e:
        assert "paginating" in str(e)
    else:
        raise AssertionError("truncated silently instead of raising")
    finally:
        _restore()


def test_paginated_range_keeps_every_day():
    """The regression: a range split across pages used to lose all but page 1."""
    _install({
        "daily_sleep": [
            {"data": [_day("2026-01-01"), _day("2026-01-02")]},
            {"data": [_day("2026-01-03")]},
        ],
        "daily_readiness": [{"data": [_day("2026-01-01")]}],
        "daily_activity": [{"data": [_day("2026-01-01")]}],
        "sleep": [
            {"data": [_sleep_period("2026-01-01")]},
            {"data": [_sleep_period("2026-01-03")]},
        ],
    })
    try:
        by_date = oura.fetch_oura_range("tok", date(2026, 1, 1), date(2026, 1, 31))
    finally:
        _restore()
    assert sorted(by_date) == ["2026-01-01", "2026-01-02", "2026-01-03"]
    # The second page of /sleep must contribute its metrics too.
    assert by_date["2026-01-03"]["hrv_avg"] == 55
    assert by_date["2026-01-03"]["total_sleep_seconds"] == 27000


# ── Window planning ──────────────────────────────────────────────────────────
def test_windows_cover_the_range_exactly_once():
    windows = oura.history_windows(date(2015, 1, 1), date(2026, 9, 8))
    assert windows[0][0] == date(2015, 1, 1)
    assert windows[-1][1] == date(2026, 9, 8)
    for (_, end), (next_start, _) in zip(windows, windows[1:]):
        assert (next_start - end).days == 1, (end, next_start)
    covered = sum((end - start).days + 1 for start, end in windows)
    assert covered == (date(2026, 9, 8) - date(2015, 1, 1)).days + 1


def test_windows_handle_degenerate_ranges():
    assert oura.history_windows(date(2027, 1, 1), date(2026, 9, 8)) == []
    single = oura.history_windows(date(2026, 9, 8), date(2026, 9, 8))
    assert single == [(date(2026, 9, 8), date(2026, 9, 8))]


def test_a_gap_in_wear_does_not_end_the_history():
    """Fixed windows, not stop-on-empty: a quiet year must not truncate."""
    windows = oura.history_windows(date(2020, 1, 1), date(2026, 1, 1))
    assert len(windows) >= 6, windows


# ── Full sync ────────────────────────────────────────────────────────────────
def test_sync_all_walks_every_window_and_writes_per_window():
    db = FakeSupabase()
    _install({}, window_mode=True)   # one day of data per window
    try:
        written = oura.sync_oura_all(
            db, "u1", "tok",
            earliest=date(2024, 1, 1), chunk_days=365,
        )
    finally:
        _restore()

    windows = oura.history_windows(date(2024, 1, 1), oura.user_today(), 365)
    assert written == len(windows), (written, len(windows))
    # One batch per window — not one big write at the end. That is what makes a
    # part-way failure keep the history it already pulled.
    assert len(db.batches) == len(windows), db.batches
    assert all(row["user_id"] == "u1" for row in db.rows)
    assert all(row.get("fetched_at") for row in db.rows)


def test_sync_all_reports_progress_for_each_window():
    db = FakeSupabase()
    _install({})
    seen = []
    try:
        oura.sync_oura_all(db, "u1", "tok",
                           earliest=oura.user_today() - timedelta(days=400),
                           chunk_days=365,
                           progress=lambda done, total, label: seen.append((done, total, label)))
    finally:
        _restore()
    assert seen, "no progress reported"
    assert seen[-1][0] == seen[-1][1], seen[-1]      # ends at 100%
    assert all(done <= total for done, total, _ in seen)


def test_sync_all_keeps_what_it_fetched_when_oura_cuts_it_off():
    """A 429 half way through must not discard the windows already written."""
    db = FakeSupabase()
    # 4 endpoints per window; fail during the third window.
    _install({}, fail_on_call=8, status=429, window_mode=True)
    try:
        oura.sync_oura_all(db, "u1", "tok",
                           earliest=oura.user_today() - timedelta(days=1200),
                           chunk_days=365)
    except oura.OuraRateLimitError:
        pass
    else:
        raise AssertionError("rate limit was not surfaced")
    finally:
        _restore()
    # Windows completed before the failure were already committed.
    assert len(db.batches) == 2, db.batches


def test_empty_history_writes_nothing_and_returns_zero():
    db = FakeSupabase()
    _install({})
    try:
        written = oura.sync_oura_all(db, "u1", "tok",
                                     earliest=date(2026, 1, 1), chunk_days=365)
    finally:
        _restore()
    assert written == 0
    assert db.batches == []


def test_windowed_sync_still_works():
    """The existing 7/30-day path must be unaffected by the refactor."""
    db = FakeSupabase()
    today = oura.user_today().isoformat()
    _install({
        "daily_sleep": [{"data": [_day(today, 91)]}],
        "daily_readiness": [{"data": [_day(today, 88)]}],
        "daily_activity": [{"data": [{"day": today, "score": 75, "steps": 9001}]}],
        "sleep": [{"data": [_sleep_period(today)]}],
    })
    try:
        written = oura.sync_oura(db, "u1", "tok", days_back=30)
    finally:
        _restore()
    assert written == 1, db.rows
    row = db.rows[0]
    assert row["sleep_score"] == 91
    assert row["readiness_score"] == 88
    assert row["steps"] == 9001
    assert row["entry_date"] == today


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
