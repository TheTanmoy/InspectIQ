"""Cost of poor quality for the Plant Quality Head: history + projected savings if issues are resolved."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require
from app.core import audit
from app.services import quality_cost
from app.services.inspection_source import get_store

router = APIRouter(prefix="/api/quality-cost", tags=["quality cost"])


class Patch(BaseModel):
    changes: dict
    note: str = ""


@router.get("")
def report(user=Depends(require("qcost:view"))):
    return quality_cost.report(get_store())


@router.put("/settings")
def update(body: Patch, user=Depends(require("qcost:edit"))):
    before = {k: quality_cost.settings().get(k) for k in body.changes}
    try:
        new = quality_cost.update_settings(body.changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.log(user, "quality_cost.settings", "quality_cost", "settings", before=before,
              after={k: new.get(k) for k in body.changes}, meta={"note": body.note[:200]} if body.note else None)
    return new
