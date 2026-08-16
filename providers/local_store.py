"""
MIR-3 · Local (file-backed) store for demos — **not for production**.

Lets the whole OAuth cycle run against a JSON file on disk instead of Kim's
Supabase, so we can demo Connect → encrypted store → sync → auto-refresh with a
real Spotify account **without touching the production schema**. Enabled by
`CONNECTIONS_BACKEND = "local"` in `.streamlit/secrets.toml`; anything else
(or absent) → real Supabase.

It mimics only the fluent surface the providers use:
    .table(name).select().eq().execute()
    .table(name).upsert(rows, on_conflict=...).execute()
    .table(name).update(patch).eq().execute()
    .table(name).delete().eq().execute()

Tokens are still Fernet-encrypted before hitting disk (crypto.py runs above
this layer), so the JSON file never contains plaintext credentials.
"""
from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace
from typing import Any

_LOCK = threading.Lock()


class _Query:
    def __init__(self, store: "LocalStore", table: str):
        self._s, self._t = store, table
        self._filters: list[tuple[str, Any]] = []
        self._op = None
        self._payload = None
        self._conflict = None

    # chainable ---------------------------------------------------------------
    def select(self, *_cols): self._op = "select"; return self
    def eq(self, k, v): self._filters.append((k, v)); return self
    def upsert(self, rows, on_conflict=None):
        self._op, self._payload, self._conflict = "upsert", rows, on_conflict; return self
    def update(self, patch): self._op, self._payload = "update", patch; return self
    def delete(self): self._op = "delete"; return self

    def _match(self, row: dict) -> bool:
        return all(row.get(k) == v for k, v in self._filters)

    def execute(self):
        with _LOCK:
            data = self._s._load()
            rows: list[dict] = data.setdefault(self._t, [])
            if self._op == "select":
                return SimpleNamespace(data=[dict(r) for r in rows if self._match(r)])
            if self._op == "upsert":
                keys = tuple((self._conflict or "").split(",")) if self._conflict else ()
                incoming = self._payload if isinstance(self._payload, list) else [self._payload]
                for new in incoming:
                    if keys:
                        k = tuple(new.get(c) for c in keys)
                        rows[:] = [r for r in rows if tuple(r.get(c) for c in keys) != k]
                    rows.append(dict(new))
                self._s._save(data)
                return SimpleNamespace(data=incoming)
            if self._op == "update":
                for r in rows:
                    if self._match(r):
                        r.update(self._payload)
                self._s._save(data)
                return SimpleNamespace(data=None)
            if self._op == "delete":
                rows[:] = [r for r in rows if not self._match(r)]
                self._s._save(data)
                return SimpleNamespace(data=None)
            raise RuntimeError("LocalStore query executed without an operation")


class LocalStore:
    """Drop-in stand-in for the Supabase client, persisted to a JSON file."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not os.path.exists(path):
            self._save({})

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    # persistence -----------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, self.path)

    def dump(self, table: str) -> list[dict]:
        return list(self._load().get(table, []))


def choose_backend(supabase, secrets) -> Any:
    """
    Return the client the providers should write to.

    `CONNECTIONS_BACKEND="local"` → LocalStore at `CONNECTIONS_LOCAL_PATH`
    (default `.mirra_local/connections.json`, gitignored). Otherwise → the real
    Supabase client, untouched.
    """
    if (secrets.get("CONNECTIONS_BACKEND") or "").lower() == "local":
        path = secrets.get("CONNECTIONS_LOCAL_PATH") or ".mirra_local/connections.json"
        return LocalStore(path)
    return supabase
