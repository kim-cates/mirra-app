"""Tests for the pure helpers in auth.py (MIR-56 follow-up).

Runs standalone (``python3 tests/test_auth_helpers.py``) and under pytest.
auth.py imports streamlit and supabase at module level; both are stubbed here
so the helpers can be tested without the app's runtime installed.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _name in ("streamlit", "supabase"):
    if _name not in sys.modules:
        stub = types.ModuleType(_name)
        stub.create_client = lambda *a, **k: None  # supabase
        stub.session_state = {}                    # streamlit
        sys.modules[_name] = stub

from auth import auth_error_kind, _display_name  # noqa: E402


class _AuthApiError(Exception):
    """Shape of supabase_auth.errors.AuthApiError: message + optional code."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def test_unconfirmed_by_code_or_message():
    assert auth_error_kind(_AuthApiError("Email not confirmed", "email_not_confirmed")) == "unconfirmed"
    assert auth_error_kind(_AuthApiError("Email not confirmed")) == "unconfirmed"


def test_existing_account():
    assert auth_error_kind(_AuthApiError("User already registered", "user_already_exists")) == "exists"
    assert auth_error_kind(_AuthApiError("A user with this email address has already been registered")) == "exists"


def test_rate_limit():
    assert auth_error_kind(_AuthApiError("email rate limit exceeded", "over_email_send_rate_limit")) == "rate_limit"


def test_everything_else_is_generic():
    assert auth_error_kind(_AuthApiError("Invalid login credentials", "invalid_credentials")) == "other"
    assert auth_error_kind(RuntimeError("connection reset")) == "other"


def test_display_name_prefers_metadata_then_email():
    user = types.SimpleNamespace(user_metadata={"username": "kim"}, email="kim@example.com")
    assert _display_name(user) == "kim"
    user = types.SimpleNamespace(user_metadata={}, email="kevin@example.com")
    assert _display_name(user) == "kevin"
    user = types.SimpleNamespace(user_metadata=None, email=None)
    assert _display_name(user, "fallback") == "fallback"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
    print("all passed")
