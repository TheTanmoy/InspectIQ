"""FinOps (AI token + run cost, for IT) and cost-benefit (for the Plant Quality Head)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require
from app.core import audit, security
from app.services import finops

router = APIRouter(prefix="/api/finops", tags=["finops"])


class SettingsPatch(BaseModel):
    section: str  # "finops" (IT) or "cba" (Plant Quality Head / Quality Manager)
    changes: dict
    note: str = ""


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), user=Depends(require("finops:view"))):
    return finops.usage(days)


@router.get("/cost-benefit")
def cost_benefit(user=Depends(require("cba:view"))):
    return finops.cost_benefit()


@router.put("/settings")
def update_settings(body: SettingsPatch, user=Depends(require("finops:view"))):
    perm = {"finops": "finops:edit", "cba": "cba:edit"}.get(body.section)
    if not perm:
        raise HTTPException(400, "section must be 'finops' or 'cba'")
    if not security.can(user["role"], perm):
        raise HTTPException(403, f"Your role ({security.ROLES[user['role']]}) cannot change {body.section} settings.")
    before = {k: finops.settings().get(k) for k in body.changes}
    try:
        new = finops.update_settings(body.section, body.changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.log(user, f"finops.settings.{body.section}", "finops", body.section, before=before,
              after={k: new.get(k) for k in body.changes}, meta={"note": body.note[:200]} if body.note else None)
    return new
