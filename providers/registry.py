"""
MIR-3 · Provider registry.

The registry is what makes "add an integration = a config change" literal: a
provider class decorates itself with `@register`, and the Connections page +
callback handler iterate whatever is registered. No vendor names are hard-coded
in the UI.

Secrets convention (per provider KEY, uppercased):
    {KEY}_CLIENT_ID
    {KEY}_CLIENT_SECRET
A single shared callback is used for every provider:
    OAUTH_REDIRECT_URI      (falls back to legacy OURA_REDIRECT_URI)

Example:
    from providers import registry
    provider = registry.build_from_secrets("spotify", st.secrets)
    url = provider.authorize_url(state=state)
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from .base import OAuthClientConfig, OAuthProvider, ProviderConfigError, ProviderMeta

# key → provider class
_REGISTRY: dict[str, type[OAuthProvider]] = {}


def register(cls: type[OAuthProvider]) -> type[OAuthProvider]:
    """
    Class decorator. Registers a provider under its `meta.key`.

    Raises at import time on a missing/duplicate key so registration bugs surface
    immediately rather than as a silently-absent connector.
    """
    meta: Optional[ProviderMeta] = getattr(cls, "meta", None)
    if meta is None or not getattr(meta, "key", None):
        raise ProviderConfigError(f"{cls.__name__} must define a class-level ProviderMeta with a key")
    if meta.key in _REGISTRY and _REGISTRY[meta.key] is not cls:
        raise ProviderConfigError(f"Duplicate provider key {meta.key!r} "
                                  f"({_REGISTRY[meta.key].__name__} vs {cls.__name__})")
    _REGISTRY[meta.key] = cls
    return cls


def available_keys() -> list[str]:
    """Registered provider keys, in registration order."""
    return list(_REGISTRY.keys())


def meta_for(key: str) -> ProviderMeta:
    """Static metadata for a key (label/color/icon) without building the provider."""
    return _provider_class(key).meta


def all_meta() -> list[ProviderMeta]:
    """Every registered provider's metadata — what the Connections page renders."""
    return [cls.meta for cls in _REGISTRY.values()]


def _provider_class(key: str) -> type[OAuthProvider]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise ProviderConfigError(
            f"Unknown provider {key!r}. Registered: {', '.join(_REGISTRY) or '(none)'}"
        )


def get_provider(key: str, config: OAuthClientConfig) -> OAuthProvider:
    """Instantiate a provider with explicit client config (test-friendly path)."""
    return _provider_class(key)(config.require())


def build_from_secrets(key: str, secrets: Mapping[str, str]) -> OAuthProvider:
    """
    Instantiate a provider by reading its client credentials from a secrets
    mapping (typically `st.secrets`). Raises ProviderConfigError with an
    actionable message if a secret is missing.
    """
    up = key.upper()
    redirect = (secrets.get("OAUTH_REDIRECT_URI")
                or secrets.get(f"{up}_REDIRECT_URI")
                or secrets.get("OURA_REDIRECT_URI", ""))  # legacy single-provider key
    config = OAuthClientConfig(
        client_id=secrets.get(f"{up}_CLIENT_ID", ""),
        client_secret=secrets.get(f"{up}_CLIENT_SECRET", ""),
        redirect_uri=redirect,
    )
    try:
        return get_provider(key, config)
    except ProviderConfigError as e:
        raise ProviderConfigError(
            f"{meta_for(key).label}: {e}. Add {up}_CLIENT_ID / {up}_CLIENT_SECRET "
            f"and OAUTH_REDIRECT_URI to .streamlit/secrets.toml."
        )


def configured_keys(secrets: Mapping[str, str]) -> list[str]:
    """
    Keys whose client credentials are present. The Connections page uses this to
    show unconfigured providers as 'coming soon' instead of erroring.
    """
    out = []
    for key in _REGISTRY:
        up = key.upper()
        if secrets.get(f"{up}_CLIENT_ID") and secrets.get(f"{up}_CLIENT_SECRET"):
            out.append(key)
    return out
