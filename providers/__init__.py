"""
MIR-3 · Provider-agnostic OAuth framework.

Public surface:
    from providers import registry, OAuthProvider, TokenBundle, ConnectionState

Importing this package eagerly imports each provider module so their
`@register` decorators run and the registry is populated. Add a new connector by
dropping a `providers/<name>.py` that subclasses `OAuthProvider` and decorates
itself with `@register`, then listing it below — that's the whole "config change".
"""
from __future__ import annotations

from .base import (
    AuthType,
    ConnectionState,
    OAuthClientConfig,
    OAuthProvider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderMeta,
    ProviderRateLimitError,
    TokenBundle,
)
from . import registry

# ── Provider registration ────────────────────────────────────────────────────
# Import for side effects (@register). Order here = display order in the UI.
#
# NOTE: the Oura provider (#26) is owned by Kim and is being built on her
# `o-auth-testing` branch — intentionally NOT shipped here so we don't duplicate
# or collide with her work. It slots into this same interface; the proposed shape
# is documented in docs/MIR-3_oauth_framework.md §5. Add its import here when it
# lands:  from . import oura as _oura  # noqa: F401
from . import spotify as _spotify  # noqa: F401  (MVP: second provider, #28)
from . import whoop as _whoop      # noqa: F401  (next: third provider)

__all__ = [
    "registry",
    "OAuthProvider",
    "OAuthClientConfig",
    "ProviderMeta",
    "TokenBundle",
    "AuthType",
    "ConnectionState",
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderConfigError",
]
