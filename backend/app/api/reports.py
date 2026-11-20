from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require
from app.core import audit, security
from app.schemas import GenerateRequest, ReportPatch, RewriteRequest, WorkflowAction
from app.services import report_builder, reports
from app.services.inspection_source import get_store

router = APIRouter(prefix="/api/reports", tags=["reports"])

ACTION_PERMISSION = {"submit": "report:submit", "review": "report:review", "request_changes": "report:review",
                     "approve": "report:approve", "release": "report:release", "send_back": "report:release",
                     "escalate": "report:edit"}


def _get(rid: str) -> dict:
    rep = reports.get(rid)
    if not rep:
        raise HTTPException(404, f"Report {rid} not found")
    return rep


@router.get("")
def list_reports(status: str = "", line: str = "", user=Depends(require("report:view"))):
    return reports.list_reports(status, line)


@router.post("/generate")
def generate(body: GenerateRequest, user=Depends(require("report:generate"))):
    try:
        draft = report_builder.generate(get_store(), body.lot, user)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    rep = reports.save_new(draft, user)
    return reports.get(rep["id"])


@router.get("/{rid}")
def get_report(rid: str, user=Depends(require("report:view"))):
    return _get(rid)


@router.patch("/{rid}")
def update_report(rid: str, body: ReportPatch, user=Depends(require("report:edit"))):
    _get(rid)
    return reports.update(rid, body.model_dump(exclude_none=True), user)


@router.post("/{rid}/actions/{action}")
def workflow(rid: str, action: str, body: WorkflowAction, user=Depends(require("report:view"))):
    perm = ACTION_PERMISSION.get(action)
    if not perm:
        raise HTTPException(400, f"Unknown action '{action}'")
    if not security.can(user["role"], perm):
        raise HTTPException(403, f"Your role ({security.ROLES[user['role']]}) cannot {action.replace('_', ' ')} reports.")
    _get(rid)
    return reports.transition(rid, action, user, body.comment)


@router.post("/{rid}/rewrite")
def rewrite(rid: str, body: RewriteRequest, user=Depends(require("report:edit"))):
    rep = _get(rid)
    if rep["status"] == "approved":
        raise HTTPException(409, "Approved reports are locked.")
    try:
        result = report_builder.rewrite_section(rep, body.section, body.instruction, user)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    audit.log(user, "report.ai_rewrite_proposed", "report", rid, meta={"section": body.section, "mode": result["mode"]})
    return result


@router.get("/{rid}/versions")
def versions(rid: str, user=Depends(require("report:view"))):
    _get(rid)
    return reports.versions(rid)


@router.get("/{rid}/audit")
def report_audit(rid: str, user=Depends(require("report:view"))):
    return audit.list_entries(entity="report", entity_id=rid, limit=100)
