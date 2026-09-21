# Registering the connector apps

What a human has to do at each vendor before a connector can be used, and what
to paste where afterwards. Everything here is a one-time step per vendor.

Decision (2026-09-07): all vendor developer apps live on a **shared Mirra
product account**, not on anyone's personal one — a Fitbit app cannot be shared
with a team, so a personal owner is a single point of failure.

## ⚠ Fitbit — the legacy platform is being shut down this month

**Read before filling anything in.** Google is turning off the legacy Fitbit Web
API — the one `providers/fitbit.py` is written against — in **September 2026**,
described by Google as a hard cutoff, not a gradual deprecation. Its replacement
is the **Google Health API** (<https://developers.google.com/health>), which is
an aggregation layer over a Google account rather than a Fitbit-specific API:
one OAuth connection returns Fitbit, Pixel Watch and third-party device data.

Consequences for us:

- OAuth tokens do not carry over. Every connected user re-consents through
  Google.
- All Google Health API scopes are **Restricted**, so access requires a privacy
  and security review — unlike the legacy Fitbit form, which issued credentials
  immediately.
- Third-party migration guides state that **new registrations on the legacy
  platform are already closed**. That is not confirmed by a first-party page;
  the fastest check is to open <https://dev.fitbit.com/apps/new> while signed in
  and see whether the form still submits.

The section below documents the legacy form as it stood, and is kept only in
case registrations are still open and a short-lived credential is useful for
testing. Do not treat it as the path to production.

## Fitbit (legacy platform) — form reference

The developer account is a plain **Google account** (Workspace accounts are not
supported). Register at <https://dev.fitbit.com/apps/new>.

| Form field | Value |
|---|---|
| Application Name | Mirra |
| Description | Daily reflection app that shows how sleep, recovery and activity line up with how you felt. |
| Application Website | https://mirra-reflections.streamlit.app/ |
| Organization | Mirra |
| Organization Website | https://mirra-reflections.streamlit.app/ |
| Terms of Service URL | https://github.com/kim-cates/mirra-app/blob/main/Mirra%20Terms%20of%20Service.md |
| Privacy Policy URL | https://github.com/kim-cates/mirra-app/blob/main/Mirra%20Privacy%20Policy.md |
| OAuth 2.0 Application Type | **Server** (not Personal — a Personal app can only read its own owner's account) |
| Callback URL | the exact value of `OAUTH_REDIRECT_URI` in the app's secrets. Fitbit requires **https**, so this is the deployed Streamlit URL, not localhost |
| Default Access Type | Read-only |

Scopes are requested by the code, not the form: `sleep heartrate activity
profile`. Intraday access needs a separate approval form and we do not use it —
daily summaries are enough.

Afterwards, `FITBIT_CLIENT_ID` and `FITBIT_CLIENT_SECRET` go into secrets.

## Strava — can be done today, no device needed

Any free Strava account can register one API application at
<https://www.strava.com/settings/api> (use the shared Mirra account, per the
decision above). No review queue for basic read scopes.

| Form field | Value |
|---|---|
| Application Name | Mirra |
| Category | Wellness |
| Website | https://mirra-reflections.streamlit.app/ |
| Application Description | Daily reflection app that shows how workouts and training load line up with how you felt. |
| Authorization Callback Domain | `mirra-reflections.streamlit.app` — **host only**, no scheme or path (the full `OAUTH_REDIRECT_URI` is sent at authorize time and must live on this domain; add `localhost` here too for local dev) |

Notes:

- The form asks for an app icon before it issues credentials — any square PNG
  works to start.
- Scopes are requested by the code (`read,activity:read_all`, comma-delimited —
  a Strava quirk). The consent screen lets the athlete untick private
  activities; sync then simply skips them.
- New apps start with a **one-athlete limit** ("your app can connect to 1
  athlete") until you request a limit increase in the same settings page —
  fine for the first test, needs the bump before the wider test group.

Afterwards, `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` go into secrets.

## Whoop — blocked until someone owns the device

WHOOP's developer platform logs in with a WHOOP account, and a WHOOP account
requires an active membership with a device. There is no way to get
`WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` without one. The connector code is
finished and waiting; register the app (up to 5 apps, redirect URI must match
`OAUTH_REDIRECT_URI` exactly) once a strap exists in the test group.

## Secrets the connectors need

In `.streamlit/secrets.toml` locally, and in the Streamlit Cloud secrets for
production — the OAuth callback lands on whichever host the user started from,
so the deployed app needs its own copy.

```toml
OAUTH_REDIRECT_URI = "https://mirra-reflections.streamlit.app/"   # one callback serves every provider
TOKEN_ENC_KEY      = "..."      # Fernet key; tokens are encrypted with it before they hit the DB
FITBIT_CLIENT_ID     = "..."
FITBIT_CLIENT_SECRET = "..."
STRAVA_CLIENT_ID     = "..."
STRAVA_CLIENT_SECRET = "..."
```

Two things that bite:

- **`TOKEN_ENC_KEY` must be the same value everywhere.** A token encrypted with
  one key cannot be read with another, so a fresh key silently invalidates every
  connection already stored. Generate once, reuse.
- Without `TOKEN_ENC_KEY` the Connections page shows "Setup required" rather
  than a broken connect flow — that message means this key, not the client id.

A provider card appears on the Connections page by itself once its
`<KEY>_CLIENT_ID` is present; no code change is needed to switch a connector on.
