"""Audit trail: every important action and every LLM call is recorded (who, what, when, before/after)."""
from __future__ import annotations

from app.core import db


def log(user: dict | None, action: str, entity: str = "", entity_id: str = "",
        before=None, after=None, meta: dict | None = None):
    user = user or {"username": "system", "role": "system"}
    with db.tx() as c:
        c.execute(
            "INSERT INTO audit_log(ts, username, role, action, entity, entity_id, before, after, meta) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (db.now_iso(), user["username"], user["role"], action, entity, entity_id,
             db.dumps(before) if before is not None else None,
             db.dumps(after) if after is not None else None,
             db.dumps(meta) if meta else None))


def log_llm_call(username: str, purpose: str, provider: str, model: str, prompt_version: str,
                 latency_ms: int, ok: bool, guardrails: dict | None = None, error: str = "", usage: dict | None = None):
    from app.services import finops  # local import: finops reads settings from the db
    u = usage or {}
    cost = finops.call_cost_usd(model, u.get("input_tokens", 0), u.get("output_tokens", 0) + u.get("thinking_tokens", 0))
    with db.tx() as c:
        c.execute(
            "INSERT INTO llm_calls(ts, username, purpose, provider, model, prompt_version, latency_ms, ok, guardrails, "
            "error, input_tokens, output_tokens, thinking_tokens, requests, estimated, cost_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (db.now_iso(), username, purpose, provider, model, prompt_version, latency_ms, int(ok),
             db.dumps(guardrails or {}), error[:500], int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)),
             int(u.get("thinking_tokens", 0)), int(u.get("requests", 0)), int(bool(u.get("estimated"))), cost))


def list_entries(entity: str = "", entity_id: str = "", username: str = "", action: str = "",
                 limit: int = 200) -> list[dict]:
    sql, params = "SELECT * FROM audit_log WHERE 1=1", []
    for col, val in (("entity", entity), ("entity_id", entity_id), ("username", username)):
        if val:
            sql += f" AND {col}=?"
            params.append(val)
    if action:
        sql += " AND action LIKE ?"
        params.append(f"%{action}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = db.query(sql, tuple(params))
    for r in rows:
        for k in ("before", "after", "meta"):
            r[k] = db.loads(r[k])
    return rows


def list_llm_calls(limit: int = 100) -> list[dict]:
    rows = db.query("SELECT * FROM llm_calls ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["guardrails"] = db.loads(r["guardrails"])
        r["ok"] = bool(r["ok"])
    return rows
