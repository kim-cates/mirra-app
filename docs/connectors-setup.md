# Registering the connector apps

What a human has to do at each vendor before a connector can be used, and what
to paste where afterwards. Everything here is a one-time step per vendor.

Decision (2026-09-07): all vendor developer apps live on a **shared Mirra
product account**, not on anyone's personal one — a Fitbit app cannot be shared
with a team, so a personal owner is a single point of failure.

## Fitbit — can be done today, no device needed

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
```

Two things that bite:

- **`TOKEN_ENC_KEY` must be the same value everywhere.** A token encrypted with
  one key cannot be read with another, so a fresh key silently invalidates every
  connection already stored. Generate once, reuse.
- Without `TOKEN_ENC_KEY` the Connections page shows "Setup required" rather
  than a broken connect flow — that message means this key, not the client id.

A provider card appears on the Connections page by itself once its
`<KEY>_CLIENT_ID` is present; no code change is needed to switch a connector on.
