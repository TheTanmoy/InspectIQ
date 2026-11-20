"""Authentication (signed tokens, stdlib only) and role-based access control."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.core import config, db

ROLES = {
    "inspector": "Inspector",
    "supervisor": "Line Supervisor",
    "quality_manager": "Quality Manager",
    "compliance_officer": "Compliance Officer",
    "plant_quality_head": "Plant Quality Head",
    "it_admin": "IT Support & FinOps",
}

# permission -> roles allowed. Single source of truth for the backend AND the frontend menu.
PERMISSIONS = {
    "inspection:view": {"inspector", "supervisor", "quality_manager", "compliance_officer", "plant_quality_head"},
    "report:view": {"inspector", "supervisor", "quality_manager", "compliance_officer", "plant_quality_head"},
    "report:generate": {"inspector", "supervisor", "quality_manager"},
    "report:edit": {"inspector", "supervisor", "quality_manager"},
    "report:submit": {"inspector", "supervisor", "quality_manager"},
    "report:review": {"supervisor", "quality_manager"},
    "report:approve": {"quality_manager"},
    "report:release": {"plant_quality_head"},  # final release of high-risk reports
    "analytics:view": {"supervisor", "quality_manager", "compliance_officer", "plant_quality_head"},
    "compliance:view": {"supervisor", "quality_manager", "compliance_officer", "plant_quality_head"},
    "compliance:edit": {"quality_manager", "compliance_officer"},
    "audit:view": {"quality_manager", "compliance_officer", "plant_quality_head", "it_admin"},
    "assistant:use": {"inspector", "supervisor", "quality_manager", "compliance_officer", "plant_quality_head"},
    "simulator:control": {"supervisor", "quality_manager"},
    # FinOps: AI token cost + support & maintenance run cost, and the tool's own business case (IT)
    "finops:view": {"it_admin", "quality_manager"},
    "finops:edit": {"it_admin"},
    "cba:view": {"it_admin", "quality_manager"},
    "cba:edit": {"it_admin"},
    # Cost of poor quality: scrap/rework history + projected savings if issues are resolved (Plant Quality Head)
    "qcost:view": {"plant_quality_head", "quality_manager"},
    "qcost:edit": {"plant_quality_head"},
}


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


# ---------------------------------------------------------------- passwords
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or hashlib.sha256(str(time.time_ns()).encode()).digest()[:16]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, _ = stored.split("$", 1)
        return hmac.compare_digest(hash_password(password, base64.b64decode(salt_b64)), stored)
    except Exception:
        return False


# ---------------------------------------------------------------- tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(user: dict) -> str:
    payload = {"sub": user["username"], "role": user["role"], "name": user["name"],
               "exp": int(time.time()) + config.TOKEN_HOURS * 3600}
    body = _b64(json.dumps(payload).encode())
    sig = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if payload["exp"] < time.time():
            return None
        user = db.query_one("SELECT username, name, role, active FROM users WHERE username=?", (payload["sub"],))
        if not user or not user["active"]:
            return None
        return {"username": user["username"], "name": user["name"], "role": user["role"]}
    except Exception:
        return None


def authenticate(username: str, password: str) -> dict | None:
    row = db.query_one("SELECT * FROM users WHERE username=? AND active=1", (username.strip().lower(),))
    if row and verify_password(password, row["password_hash"]):
        return {"username": row["username"], "name": row["name"], "role": row["role"]}
    return None


def seed_users(users: list[dict]):
    with db.tx() as c:
        for u in users:
            exists = c.execute("SELECT 1 FROM users WHERE username=?", (u["username"],)).fetchone()
            if not exists:
                c.execute("INSERT INTO users(username, name, role, password_hash) VALUES (?,?,?,?)",
                          (u["username"], u["name"], u["role"], hash_password(u["password"])))
