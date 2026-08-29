"""
MIR-56 · Create Supabase Auth accounts for existing users and fill users.auth_id.

Run BETWEEN step 1 and step 2 of docs/migrations/MIR-56_supabase_auth.sql.

Why a script and not SQL: auth.users can only be written through the Auth admin
API, not with plain INSERTs. And passwords genuinely cannot be carried over —
the existing hashes are unsalted SHA256, Supabase stores bcrypt. So each account
is created with a fresh random password, and every user sets their own via the
reset link. There is no way around this; it is the visible cost of the migration.

Requires the SERVICE ROLE key (not anon) — admin endpoints only accept it. Never
put that key in Streamlit secrets or commit it; export it for this run only:

    export SUPABASE_URL=https://<project>.supabase.co
    export SUPABASE_SERVICE_KEY=<service_role key>
    python scripts/migrate_users_to_auth.py --dry-run   # inspect first
    python scripts/migrate_users_to_auth.py             # then execute

Every user needs an email. Rows without one are reported and skipped — decide
per user (ask them, or set a placeholder) rather than inventing addresses.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

try:
    from supabase import create_client
except ImportError:
    sys.exit("pip install supabase")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would happen, change nothing")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return int(bool(sys.stderr.write(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set (service_role, not anon)\n")))

    db = create_client(url, key)

    rows = (db.table("users").select("id,username,email,auth_id").execute().data) or []
    todo = [r for r in rows if not r.get("auth_id")]
    missing_email = [r for r in todo if not (r.get("email") or "").strip()]
    todo = [r for r in todo if (r.get("email") or "").strip()]

    print(f"users total: {len(rows)} | need migrating: {len(todo) + len(missing_email)}")
    if missing_email:
        print("\n⚠ no email — skipped, handle these by hand:")
        for r in missing_email:
            print(f"   - {r['username']} (id {r['id']})")

    if not todo:
        print("\nnothing to do.")
        return 0

    print("\nwill create auth accounts for:")
    for r in todo:
        print(f"   - {r['username']:<20} {r['email']}")

    if args.dry_run:
        print("\n--dry-run: nothing was changed.")
        return 0

    ok, failed = 0, []
    for r in todo:
        try:
            created = db.auth.admin.create_user({
                "email": r["email"],
                "password": secrets.token_urlsafe(32),  # throwaway; user resets it
                "email_confirm": True,                  # no confirmation mail for a migration
                "user_metadata": {"username": r["username"], "migrated_from": r["id"]},
            })
            auth_id = created.user.id
            db.table("users").update({"auth_id": auth_id}).eq("id", r["id"]).execute()
            print(f"  ✓ {r['username']} -> {auth_id}")
            ok += 1
        except Exception as e:                      # noqa: BLE001 - report and continue
            print(f"  ✗ {r['username']}: {e}")
            failed.append(r["username"])

    print(f"\nmigrated {ok}/{len(todo)}")
    if failed:
        print("failed:", ", ".join(failed))
        print("Fix these before running step 2 — it requires auth_id on every row.")
        return 1

    print("\nNext: 1) verify `select count(*) from public.users where auth_id is null;` returns 0")
    print("      2) run step 2 of docs/migrations/MIR-56_supabase_auth.sql")
    print("      3) send everyone a password-reset link (Supabase > Authentication > Users)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
