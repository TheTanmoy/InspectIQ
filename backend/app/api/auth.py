from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import current_user
from app.core import audit, security
from app.schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest):
    user = security.authenticate(body.username, body.password)
    if not user:
        audit.log({"username": body.username[:50], "role": "unknown"}, "auth.login_failed", "user", body.username[:50])
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    audit.log(user, "auth.login", "user", user["username"])
    return {"token": security.create_token(user), "user": user,
            "role_label": security.ROLES[user["role"]], "permissions": security.permissions_for(user["role"])}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"user": user, "role_label": security.ROLES[user["role"]],
            "permissions": security.permissions_for(user["role"])}


@router.get("/demo-users")
def demo_users():
    """Shown on the login screen so judges can switch roles quickly (synthetic demo accounts)."""
    return [{"username": u, "role": r, "role_label": security.ROLES[r]} for u, r in
            (("inspector", "inspector"), ("supervisor", "supervisor"), ("qm", "quality_manager"),
             ("compliance", "compliance_officer"), ("head", "plant_quality_head"), ("itops", "it_admin"))]
