#!/usr/bin/env python3
"""
Prove the Fitbit connector end-to-end without owning a tracker.

Fitbit lets you POST a sleep log by hand, which is the whole trick: we write one
night into the connected account, read it back through the same date-range call
`FitbitProvider.sync()` uses, run the real rollup on it, and then delete the log
again so the tester's account is left as we found it.

What it does NOT prove: that a real device's payload looks like this. Manual logs
come back as `type: "classic"` — no sleep stages — so `minutes_deep/light/rem`
stay NULL, exactly the branch `test_classic_log_keeps_duration_but_no_stages`
covers. Stage data still needs one night on a real Fitbit.

Usage:
    export FITBIT_ACCESS_TOKEN=...        # from a completed OAuth connect
    python3 scripts/fitbit_verify_cycle.py                # dry run, prints the row
    python3 scripts/fitbit_verify_cycle.py --keep-log     # leave the log in place
    python3 scripts/fitbit_verify_cycle.py --write USER_ID  # also upsert to Supabase

The token comes from the environment on purpose — this script never reads or
writes credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from providers.fitbit import (  # noqa: E402
    FITBIT_API_BASE,
    REQUEST_TIMEOUT,
    aggregate_fitbit_daily,
)

SLEEP_MINUTES = 7 * 60 + 12          # a plausible night, not a round number
START_TIME = "23:30"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept-Language": "en_US"}


def create_sleep_log(token: str, day: str) -> dict:
    """POST one manual sleep log. Fitbit dates it by the day you woke up."""
    resp = requests.post(
        f"{FITBIT_API_BASE}/1.2/user/-/sleep.json",
        headers=_headers(token),
        params={"date": day, "startTime": START_TIME,
                "duration": SLEEP_MINUTES * 60 * 1000},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise SystemExit(f"create sleep log failed: {resp.status_code} {resp.text[:300]}")
    return resp.json().get("sleep") or {}


def delete_sleep_log(token: str, log_id) -> bool:
    resp = requests.delete(
        f"{FITBIT_API_BASE}/1.2/user/-/sleep/{log_id}.json",
        headers=_headers(token), timeout=REQUEST_TIMEOUT,
    )
    return resp.status_code in (200, 204)


def read_range(token: str, start: str, end: str) -> dict:
    resp = requests.get(
        f"{FITBIT_API_BASE}/1.2/user/-/sleep/date/{start}/{end}.json",
        headers=_headers(token), timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise SystemExit(f"read range failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-log", action="store_true",
                    help="do not delete the sleep log afterwards")
    ap.add_argument("--write", metavar="USER_ID",
                    help="also upsert the rollup into Supabase for this user id")
    args = ap.parse_args()

    token = os.environ.get("FITBIT_ACCESS_TOKEN")
    if not token:
        raise SystemExit("set FITBIT_ACCESS_TOKEN (an access token from a completed connect)")

    today = datetime.now(timezone.utc).date()
    day = (today - timedelta(days=1)).isoformat()

    print(f"1. creating a manual sleep log for {day} ({SLEEP_MINUTES} min from {START_TIME})")
    created = create_sleep_log(token, day)
    log_id = created.get("logId")
    print(f"   logId={log_id} type={created.get('type')} isMainSleep={created.get('isMainSleep')}")

    try:
        print("2. reading it back through the date-range call sync() uses")
        payload = read_range(token, day, today.isoformat())
        logs = payload.get("sleep") or []
        print(f"   {len(logs)} log(s) returned; ours present: "
              f"{any(l.get('logId') == log_id for l in logs)}")

        print("3. running the real rollup")
        rows = aggregate_fitbit_daily(logs, [], [], [])
        row = rows.get(day)
        if row is None:
            print("   !! no row for that day — the manual log did not come back in the range")
            return 1
        printable = {k: v for k, v in row.items() if k != "raw"}
        print("   " + json.dumps(printable, indent=2, ensure_ascii=False).replace("\n", "\n   "))

        if args.write:
            print("4. upserting into Supabase")
            import streamlit as st  # noqa: E402  (only needed for this branch)
            from supabase import create_client  # noqa: E402
            sb = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
            row["user_id"] = args.write
            row["fetched_at"] = datetime.now(timezone.utc).isoformat()
            sb.table("fitbit_daily").upsert([row], on_conflict="user_id,entry_date").execute()
            print("   upserted; read it back with the user's own session to check RLS")
    finally:
        if log_id and not args.keep_log:
            ok = delete_sleep_log(token, log_id)
            print(f"5. cleanup: sleep log {log_id} deleted: {ok}")
        elif log_id:
            print(f"5. cleanup skipped, sleep log {log_id} left in the account")

    return 0


if __name__ == "__main__":
    sys.exit(main())
