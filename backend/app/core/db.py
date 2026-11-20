"""SQLite storage (built into Python - nothing to install).

Tables: users, reports, report_versions, rule_versions, meta, audit_log, llm_calls.
JSON payloads are stored as TEXT and decoded by the helpers below.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from app.core import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, name TEXT, role TEXT, password_hash TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, line TEXT, lot TEXT, shift TEXT, status TEXT,
    created_by TEXT, created_at TEXT, updated_at TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS report_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT, version INTEGER,
    changed_by TEXT, changed_at TEXT, change_note TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS rule_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT, version INTEGER, rulebook_version INTEGER,
    changed_by TEXT, changed_at TEXT, change_note TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, role TEXT, action TEXT,
    entity TEXT, entity_id TEXT, before TEXT, after TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, purpose TEXT, provider TEXT, model TEXT,
    prompt_version TEXT, latency_ms INTEGER, ok INTEGER, guardrails TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log(entity, entity_id);
CREATE INDEX IF NOT EXISTS ix_reports_status ON reports(status);
"""

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        # migrations: token usage + cost per AI call (FinOps). Safe to run on every start.
        have = {r[1] for r in _conn.execute("PRAGMA table_info(llm_calls)")}
        for col, typ in (("input_tokens", "INTEGER DEFAULT 0"), ("output_tokens", "INTEGER DEFAULT 0"),
                         ("thinking_tokens", "INTEGER DEFAULT 0"), ("requests", "INTEGER DEFAULT 0"),
                         ("estimated", "INTEGER DEFAULT 0"), ("cost_usd", "REAL DEFAULT 0")):
            if col not in have:
                _conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {typ}")
        _conn.commit()
        _conn.commit()
    return _conn


def reset_connection():
    """Used by tests to point at a fresh database."""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


def loads(text: str | None):
    return json.loads(text) if text else None


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def get_meta(key: str, default: str = "") -> str:
    row = query_one("SELECT value FROM meta WHERE key=?", (key,))
    return row["value"] if row else default


def set_meta(key: str, value: str):
    with tx() as c:
        c.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
