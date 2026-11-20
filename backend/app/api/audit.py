from fastapi import APIRouter, Depends, Query

from app.api.deps import require
from app.core import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])
VIEW = Depends(require("audit:view"))


@router.get("")
def entries(entity: str = "", entity_id: str = "", username: str = "", action: str = "",
            limit: int = Query(200, le=1000), user=VIEW):
    return audit.list_entries(entity, entity_id, username, action, limit)


@router.get("/llm")
def llm_calls(limit: int = Query(100, le=500), user=VIEW):
    return audit.list_llm_calls(limit)
