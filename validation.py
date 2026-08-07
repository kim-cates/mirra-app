"""Input validation helpers for Mirra (MIR-1, sub-issue #17).

Pure functions — no Streamlit, no DB — so they are trivially testable and
reusable by both the Create User page and the Profile Settings edit flow.

Convention: every ``validate_*`` returns ``(is_valid: bool, error: str | None)``.
Profile fields are OPTIONAL (MIR-1: no field blocks account creation), so an
empty/whitespace value is treated as valid. Callers that require a value should
check for emptiness separately.
"""

import re

# Practical email shape (not full RFC 5322 — deliberately). Good enough to
# catch typos while accepting real-world addresses.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")

# Keep digits and a single leading "+"; everything else (spaces, dashes,
# parentheses, dots) is formatting we strip before checking length.
_PHONE_STRIP_RE = re.compile(r"[\s().\-]")
_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")  # E.164: 7–15 digits, no leading zero


def normalize_email(value: str) -> str:
    """Trim surrounding whitespace and lower-case the address for storage."""
    return (value or "").strip().lower()


def validate_email(value: str) -> tuple[bool, str | None]:
    """Validate an email address. Empty is allowed (optional field)."""
    email = normalize_email(value)
    if not email:
        return True, None
    if len(email) > 254:
        return False, "Email is too long."
    if not _EMAIL_RE.match(email):
        return False, "Enter a valid email address (e.g. you@example.com)."
    return True, None


def normalize_phone(value: str) -> str:
    """Strip formatting, keeping an optional leading '+' and the digits."""
    raw = (value or "").strip()
    if not raw:
        return ""
    plus = raw.startswith("+")
    digits = _PHONE_STRIP_RE.sub("", raw)
    digits = re.sub(r"\D", "", digits)
    return ("+" + digits) if plus else digits


def validate_phone(value: str) -> tuple[bool, str | None]:
    """Validate a phone number (E.164-ish). Empty is allowed (optional field)."""
    if not (value or "").strip():
        return True, None
    phone = normalize_phone(value)
    if not _PHONE_RE.match(phone):
        return False, "Enter a valid phone number (7–15 digits, e.g. +18085551234)."
    return True, None
