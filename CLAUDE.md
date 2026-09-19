# CLAUDE.md — Mirra (mirra-app)

Operating rules for AI assistants working in this repo. Distilled from the founders' working agreement. Keep it current.

> **Product:** Mirra — "Where patterns become awareness." A daily-reflection / journaling app (Streamlit + Supabase + Anthropic Claude) with Oura biometric integration and NLP pattern discovery.
> **Full foundation** (transcribed founder meetings + analyses + skills) lives **outside this repo** in the sibling folder `../Transcripts/` — read `../Transcripts/00_MASTER_big-picture.md`, `../Transcripts/RULES_and_WORKFLOW.md`, and `../Transcripts/skills/` when available.

## 🔴 Non-negotiables

1. **Never merge into `main` without Kim's explicit review and approval.** Kim owns the repo (`github.com/kim-cates/mirra-app`) and reviews every change. Commit freely to `igor-dev` / `feature/*`; **prepare** PRs but **do not merge** — hand them to Kim. Disable/avoid Claude/VS Code auto-merge.
2. **Treat user data as HIPAA-grade.** Never expose users' mental/physical-health data to advertisers or third parties.
3. **DB schema changes go through the Supabase SQL editor AND get mirrored into `migrations.sql`.** No un-versioned schema drift. Add RLS to every per-user table.

## Git workflow

```
git checkout main && git pull origin main
git checkout -b feature/<task-slug>     # one branch per board task; never work on main
# build with small, clear commits
git push -u origin feature/<task-slug>  # open a PR → Kim reviews → GitHub checks pass → Kim merges
```
- Tasks come from the **GitHub Projects** board; work is contracted per task.
- Keep the AI scoped to this repo folder.

## Database (Supabase)

- Client: `create_client(SUPABASE_URL, SUPABASE_KEY)` — secrets in `.streamlit/secrets.toml` (**gitignored**, get from Kim).
- Tables: `users` (custom auth, SHA256 hash), `reflections` (unique on `user_id, entry_date`), `oura_daily`, `oura_credentials` (both in `migrations.sql`, RLS on).
- **⚠ Identity gotcha:** the app uses a custom `public.users` table, but `oura_*` tables FK to `auth.users(id)` with RLS on `auth.uid()`. Confirm the authoritative identity with Kim before adding per-user tables. `users`/`reflections` DDL is **not** yet in `migrations.sql`.

## Architecture / product principles

- **Foundation-first, don't over-engineer the MVP.** Roadmap order: profile/onboarding → OAF (seamless OAuth) → connectors → insights/personalization.
- New connectors = **isolated "models"** (own module), MVP-level = plain **API + preprocessing** (agent-per-connector is a later phase).
- Nothing in the stack is locked in (Streamlit especially) — but don't swap infra without agreement.

## Working with the founders

- **Sustainable pace**; end-of-month is a soft target. Communicate compute-blocked days.
- **Validate insight UX with real people** before polishing.
- When a task requires merging to `main`, an infra swap, or would expose user data — **stop and flag it.**
