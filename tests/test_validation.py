"""Tests for validation helpers (MIR-1 #17).

Runs standalone (``python3 tests/test_validation.py``) and under pytest.
No third-party test framework required.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation import (  # noqa: E402
    normalize_email,
    normalize_phone,
    validate_email,
    validate_phone,
)


def test_email_valid():
    for v in ["you@example.com", "First.Last+tag@sub.domain.co", "  A@B.io  "]:
        ok, err = validate_email(v)
        assert ok and err is None, (v, err)


def test_email_invalid():
    for v in ["nope", "a@b", "a@@b.com", "a b@c.com", "@x.com", "x@.com"]:
        ok, err = validate_email(v)
        assert not ok and err, (v,)


def test_email_optional_empty():
    for v in ["", "   ", None]:
        ok, err = validate_email(v)
        assert ok and err is None, (v,)


def test_email_normalize():
    assert normalize_email("  You@Example.COM ") == "you@example.com"


def test_phone_valid():
    for v in ["+18085551234", "808 555 1234", "(808) 555-1234", "+380 44 123 45 67"]:
        ok, err = validate_phone(v)
        assert ok and err is None, (v, err)


def test_phone_invalid():
    for v in ["123", "abcdef", "+0123456789", "++1808", "0000"]:
        ok, err = validate_phone(v)
        assert not ok and err, (v,)


def test_phone_optional_empty():
    for v in ["", "   ", None]:
        ok, err = validate_phone(v)
        assert ok and err is None, (v,)


def test_phone_normalize():
    assert normalize_phone("(808) 555-1234") == "8085551234"
    assert normalize_phone("+1 808-555-1234") == "+18085551234"


def _run():
    fns = [g for n, g in sorted(globals().items()) if n.startswith("test_") and callable(g)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
