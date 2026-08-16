"""
MIR-3 · Token encryption — issue #27 ("tokens stored encrypted").

Design skeleton. Access/refresh tokens are secrets; they must not sit in the DB
as plaintext. We wrap them with Fernet (AES-128-CBC + HMAC) using a key held in
app secrets, so a DB dump alone can't be replayed against a vendor API.

    key = st.secrets["TOKEN_ENC_KEY"]   # 32 url-safe base64 bytes, generated once
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

`token_store` calls `encrypt()` before writing and `decrypt()` after reading.
A stored value is prefixed with a scheme tag ("v1:") so we can migrate schemes
later and so unencrypted legacy rows (from the single-provider Oura table) are
detectable and can be lazily re-wrapped.

`cryptography` is imported lazily so the package still imports on a box that
hasn't installed it yet (this branch is skeleton-only). Add `cryptography` to
requirements.txt when #27 is implemented.
"""
from __future__ import annotations

from typing import Optional

_SCHEME = "v1:"


class TokenCryptoError(Exception):
    """Encryption/decryption failed or is misconfigured."""


def _fernet(key: str):
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:  # pragma: no cover - skeleton guard
        raise TokenCryptoError(
            "cryptography not installed — add it to requirements.txt for #27."
        ) from e
    if not key:
        raise TokenCryptoError("TOKEN_ENC_KEY is empty — set it in secrets.toml.")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise TokenCryptoError(f"Invalid TOKEN_ENC_KEY: {e}") from e


def encrypt(plaintext: Optional[str], key: str) -> Optional[str]:
    """Encrypt a token for storage. None passes through (e.g. absent refresh token)."""
    if plaintext is None:
        return None
    token = _fernet(key).encrypt(plaintext.encode()).decode()
    return _SCHEME + token


def decrypt(stored: Optional[str], key: str) -> Optional[str]:
    """
    Decrypt a stored token. Values without the scheme prefix are treated as
    legacy plaintext and returned as-is (lets the Oura table migrate lazily).
    """
    if stored is None:
        return None
    if not stored.startswith(_SCHEME):
        return stored  # legacy plaintext — caller may re-wrap on next write
    try:
        return _fernet(key).decrypt(stored[len(_SCHEME):].encode()).decode()
    except TokenCryptoError:
        raise
    except Exception as e:
        raise TokenCryptoError(f"Token decryption failed: {e}") from e


def is_encrypted(stored: Optional[str]) -> bool:
    return bool(stored) and stored.startswith(_SCHEME)
