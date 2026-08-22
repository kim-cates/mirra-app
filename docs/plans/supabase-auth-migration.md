# Plan — move sign-in to Supabase Auth and turn on RLS

> **Status: PROPOSAL.** Nothing implemented. Needs Kim's go-ahead before any code
> or schema changes, and a lane agreement with the MIR-1 session (this touches
> `auth.py`, which is their territory).

## 1. Why

The app stores everything in Supabase but doesn't use Supabase's protection.
`auth.py` runs its own SHA256 password check against the custom `public.users`
table; there is no Supabase Auth session, so `auth.uid()` is null and RLS
matches nothing. That's why RLS is off on `users`, `reflections` and the
`oura_*` tables.

The consequence, today: the app connects with the **anon key, which ships to the
client**. With RLS off, anyone who extracts that key can read **every user's
journal entries and biometrics** — not just their own. For mental-health data
plus biometrics that is the real exposure, and it exists independently of MIR-3.

Every new per-user table added on `public.users` also raises the cost of the
eventual move. Right now that cost is at its lowest: a handful of users, 7 tables.

## 2. What's actually affected

| Surface | Count |
|---|---|
| Python files referencing `user_id` | 12 (excluding `delete/`) |
| Call sites on `table("users")` | 39 |
| Per-user tables | `users`, `reflections`, `oura_credentials`, `oura_daily`, `oura_oauth_states`, `connections`, `spotify_daily` |

## 3. The one hard constraint: passwords cannot be migrated

Existing hashes are **unsalted SHA256**; Supabase Auth stores bcrypt and will not
import them. So existing accounts cannot be moved silently — each user must set a
password again (or sign in by magic link).

With ~5 users (Kim, Igor, Kevin, Ashley, Antonia) the honest approach is to
re-invite them. This is the main user-visible cost of the migration and should be
communicated before it happens, not after.

## 4. Two routes

**Route A — link table (lower risk).** Keep `public.users.id` as the app's key;
add `auth_id uuid references auth.users(id)`. RLS policies dereference it:

```sql
using (user_id in (select id from public.users where auth_id = auth.uid()))
```

- ✅ No re-keying of existing rows — `reflections`, `oura_daily` etc. stay as they are
- ✅ Reversible; can ship incrementally, table by table
- ❌ Every policy carries a subquery (fine at this scale, indexed on `auth_id`)
- ❌ Two ids coexist — the ambiguity we're trying to remove stays, just documented

**Route B — re-key onto `auth.users` (clean end state).** `public.users` becomes a
profile table whose PK *is* the auth id; every per-user table's `user_id` is
rewritten to the new ids.

- ✅ One identity, simple policies: `using (auth.uid() = user_id)`
- ✅ Matches what `migrations.sql` already *claims* for the `oura_*` tables
- ❌ Requires rewriting FKs across 7 tables in one transaction, with a backup
- ❌ Bigger single step; needs a maintenance window (trivial at 5 users)

**Recommendation: Route B.** The whole point is to stop having two notions of
identity, and Route A preserves that split. At current data volume the rewrite is
minutes of work; at 500 users it is a project.

## 5. Steps (Route B)

1. **Backup** — export `users`, `reflections`, `oura_*` from Supabase. Non-negotiable.
2. **Enable Supabase Auth** (email/password) in the project settings.
3. **Create auth accounts** for the existing users; record the mapping
   `old users.id → auth.users.id`.
4. **Rewrite `auth.py`** around `supabase.auth.sign_up` / `sign_in_with_password` /
   `sign_out`; session comes from Supabase, not `st.session_state` alone.
   *(This also fixes the "F5 logs you out" problem — Supabase issues a refresh
   token that survives a reload, which `session_state` never did.)*
5. **Migrate data** in one transaction: add the new id column, backfill via the
   mapping, repoint FKs, drop the old column.
6. **Turn on RLS everywhere** — `users`/profile, `reflections`, `oura_*`, and the
   MIR-3 tables — all `auth.uid() = user_id`.
7. **Point MIR-3 at `auth.users`** — swap the FKs in #55 (the variant is already
   drafted in `docs/migrations/`), then create the tables.
8. **Verify**: sign-in, reflection write, Oura sync, Spotify connect; and confirm
   with the anon key that user A cannot read user B's rows.

## 6. Where Spotify fits

Spotify's code, UI and tests are already merged and verified live. It's blocked
only on its three tables existing. Those tables should be created **after** step 6,
against `auth.users` — so Spotify ships immediately after the migration rather
than being re-migrated later. Concretely: #55 stays open until step 7, then gets
the FK swap.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Users locked out mid-migration | Do it in one window; tell the testers first |
| Password reset is unavoidable | Re-invite the ~5 users by hand |
| Data loss on FK rewrite | Full export first; run as one transaction |
| Conflicts with the MIR-1 session | Agree lanes before starting — `auth.py` can only have one owner |

## 8. Open questions for Kim

1. Route A or B (recommendation: B).
2. OK to require the existing testers to set a new password?
3. Who implements — this session or the MIR-1 session? Only one can hold `auth.py`.
4. Do it before or after the friends-testing round? (Doing it after means migrating
   more real data.)
