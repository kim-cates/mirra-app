"""Tests for the MIR-3 OAuth provider framework (#25/#27/#28/#29).

Runs standalone (``python3 tests/test_providers.py``) and under pytest.
Pure/offline — no network, no DB, no Streamlit.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import providers  # noqa: E402  (populates the registry on import)
from providers import registry  # noqa: E402
from providers.base import (  # noqa: E402
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    TokenBundle,
)


# ── Registry ──────────────────────────────────────────────────────────────────
def test_registry_has_shipped_providers():
    keys = registry.available_keys()
    assert "spotify" in keys and "whoop" in keys, keys


def test_registry_excludes_oura_and_template():
    # Oura (#26) is Kim's lane; _template.py must never auto-register.
    keys = registry.available_keys()
    assert "oura" not in keys, keys
    assert "template" not in keys, keys


# ── TokenBundle expiry math ───────────────────────────────────────────────────
def test_token_bundle_parses_expires_in():
    b = TokenBundle.from_oauth_response(
        {"access_token": "a", "refresh_token": "r", "expires_in": 3600, "scope": "x"})
    assert b.access_token == "a" and b.refresh_token == "r" and b.scopes == "x"
    assert b.expires_at is not None and b.expires_at.tzinfo is not None


def test_needs_refresh_true_near_expiry():
    assert TokenBundle.from_oauth_response({"access_token": "a", "expires_in": 60}).needs_refresh()


def test_needs_refresh_false_when_fresh():
    assert not TokenBundle.from_oauth_response({"access_token": "a", "expires_in": 3600}).needs_refresh()


def test_non_expiring_token_never_refreshes():
    # PAT-style: no expiry ⇒ never needs refresh.
    assert not TokenBundle(access_token="a").needs_refresh()


def test_refresh_fallback_preserves_old_token():
    # Vendors that omit refresh_token on refresh reuse the previous one.
    b = TokenBundle.from_oauth_response({"access_token": "new", "expires_in": 10},
                                        fallback_refresh="old")
    assert b.refresh_token == "old"


# ── Authorize URL / CSRF state ────────────────────────────────────────────────
def test_authorize_url_carries_state_and_config():
    p = registry.build_from_secrets("spotify", {
        "SPOTIFY_CLIENT_ID": "cid", "SPOTIFY_CLIENT_SECRET": "sec",
        "OAUTH_REDIRECT_URI": "https://app/callback",
    })
    url = p.authorize_url(state="spotify:nonce123")
    assert "state=spotify%3Anonce123" in url  # provider key + nonce survive encoding
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fapp%2Fcallback" in url


# ── Config errors are actionable, not stack traces ────────────────────────────
def test_missing_secrets_raise_config_error():
    try:
        registry.build_from_secrets("spotify", {})  # no creds
    except ProviderConfigError as e:
        assert "CLIENT_ID" in str(e)
    else:
        assert False, "expected ProviderConfigError"


def test_unknown_provider_raises():
    try:
        registry.build_from_secrets("nope", {})
    except ProviderConfigError:
        pass
    else:
        assert False, "expected ProviderConfigError for unknown key"


# ── Error taxonomy ────────────────────────────────────────────────────────────
def test_error_hierarchy():
    assert issubclass(ProviderAuthError, ProviderError)
    assert issubclass(ProviderRateLimitError, ProviderError)
    assert issubclass(ProviderConfigError, ProviderError)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
