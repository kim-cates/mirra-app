# Data sources — what we can actually capture

Living document. Written 2026-09-07 from the Igor x Kim call ("we need to understand what we
can actually connect before we write the onboarding questions"). It is filled in *alongside*
building connectors, not ahead of them — a source moves from "assumed" to "verified" only when
someone has read the vendor's current docs or shipped the connector.

## Why this exists

Onboarding questions, the insight UX, and the "one variable on a time signature" visuals all
depend on which signals exist. Designing them before this map is settled means rebuilding them.
The map is also where the **build vs. aggregator** decision gets made (see below).

## Umbrella categories

The app does not need fifty fields. It needs a few axes a person recognises about themselves:

| Axis | Signals that feed it | Sources |
|---|---|---|
| Sleep | duration, efficiency, timing, debt | Oura, Whoop, Fitbit, Apple Watch |
| Recovery / stress | HRV, resting HR, body temp, respiratory rate | Oura, Whoop, Fitbit |
| Activity | steps, workouts, active minutes, strain | Oura, Whoop, Fitbit, Apple Watch |
| Productivity / attention | screen time, app categories, browsing | see "hard" section |
| Mood context | listening volume, late-night listening | Spotify |
| Self-report | the daily reflection itself | Mirra |

## Status per source

| Source | Verdict | Notes |
|---|---|---|
| **Oura** | shipped | `oura.py`, own pre-MIR-3 code path |
| **Spotify** | shipped | `providers/spotify.py`; audio-features (valence/energy) are closed to apps created after 2024-11-27, so mood-from-music is NOT available — only volume/timing |
| **Whoop** | code shipped, **gated on hardware** | API v2, `sync()` -> `whoop_daily`. WHOOP's developer dashboard logs in with a WHOOP account, and that requires an active membership with a device — so the client credentials cannot be obtained at all until someone in the test group owns a strap |
| **Fitbit** | code shipped, registerable today | `sync()` -> `fitbit_daily`: sleep stages, resting HR, HRV, steps. No device needed to register (see `docs/connectors-setup.md`), and a manual sleep log can prove the cycle end-to-end without a tracker |
| **Garmin** | parked | Health API is partner-approval only; unpredictable lead time |
| **Apple Watch** | blocked by design | No cloud API exists. HealthKit is on-device iOS only. Three workarounds: (a) our own iOS companion, (b) a user-installed exporter app posting to our endpoint, (c) an aggregator with a mobile SDK. All three are product decisions, not a connector |
| **Google Fit / Android** | blocked by design | Fit REST API retired; Health Connect is on-device Android only. Same three workarounds |
| **Screen time** | blocked by design | Neither iOS nor Android exposes it off-device without our own mobile app (on iOS the report is sandboxed). Desktop-only alternatives: a browser extension, or RescueTime's API |

Anything marked "blocked by design" is not a missing integration — it is a question of whether
Mirra ships a mobile app or buys an aggregator.

## The one strategic decision for Kim

Two roads, and the answer changes the roadmap:

1. **Keep building per-vendor connectors.** Cheap per source (~1-2 days each on the existing
   framework), full control of the data, no vendor fee. But it structurally cannot reach Apple
   Watch, Android, or screen time.
2. **Add an aggregator** (Terra / Vital / Rook / Spike class). One integration covers many
   devices *including* Apple Health via their mobile SDK. Costs money per user and puts a third
   party between us and health data — which needs a hard look against our HIPAA-grade rule.

Recommendation: finish Whoop and Fitbit ourselves (they are days, and they prove the framework),
and treat the aggregator as a separate decision to make once we know how many testers actually
own an Apple Watch. Do not start a native mobile app for the MVP.

## Track order agreed on the call (2026-09-07)

1. This map — grows as connectors land, not a separate research phase.
2. **Whoop `sync()`** — done, `feature/connectors-whoop-fitbit`.
3. **Fitbit connector** — done, same branch. Both need vendor apps registered before a live run.
4. **Voice-to-text reflections** — parallel session, `feature/voice-to-text-reflections`.
5. **PWA / mobile polish** — deliberately last, right before MVP: it is tangled with design and
   flow, and building it now means rebuilding it after Kim's UI blueprint.
