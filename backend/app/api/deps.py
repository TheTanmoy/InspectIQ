"""Shared FastAPI dependencies: current user + permission checks (role-based access control)."""
from fastapi import Depends, Header, HTTPException, Query

from app.core import security


def current_user(authorization: str = Header(default=""), token: str = Query(default="")) -> dict:
    """Token from 'Authorization: Bearer <token>' (or ?token= for <img> tags that cannot send headers)."""
    raw = authorization.removeprefix("Bearer ").strip() if authorization else token
    user = security.decode_token(raw) if raw else None
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in again (missing or expired session).")
    return user


def require(permission: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if not security.can(user["role"], permission):
            raise HTTPException(status_code=403,
                                detail=f"Your role ({security.ROLES.get(user['role'], user['role'])}) "
                                       f"is not allowed to do this ({permission}).")
        return user
    return checker
