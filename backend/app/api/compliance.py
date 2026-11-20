from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require
from app.core import audit
from app.schemas import RuleCreate, RuleImport, RuleUpdate
from app.services import compliance, reports

router = APIRouter(prefix="/api/compliance", tags=["compliance"])
VIEW = Depends(require("compliance:view"))
EDIT = Depends(require("compliance:edit"))


def _open_outcomes() -> dict[str, dict]:
    return {r["id"]: {"score": r["compliance_score"], "blocking": r["blocking_failures"], "lot": r["lot"]}
            for r in reports.list_reports() if r["status"] != "approved"}


def _impact(before: dict, after: dict) -> list[dict]:
    out = []
    for rid, b in before.items():
        a = after.get(rid)
        if a and (a["score"] != b["score"] or a["blocking"] != b["blocking"]):
            out.append({"report_id": rid, "lot": b["lot"], "score_before": b["score"], "score_after": a["score"],
                        "blocking_before": b["blocking"], "blocking_after": a["blocking"]})
    return out


@router.get("/rules")
def rules(user=VIEW):
    return {"rulebook_version": compliance.rulebook_version(), "rules": compliance.list_rules(),
            "rule_types": sorted(compliance.EVALUATORS), "editable_fields": sorted(compliance.EDITABLE_FIELDS)}


@router.get("/rules/{rule_id}/history")
def history(rule_id: str, user=VIEW):
    return compliance.history(rule_id)


@router.put("/rules/{rule_id}")
def update(rule_id: str, body: RuleUpdate, user=EDIT):
    if not compliance.get_rule(rule_id):
        raise HTTPException(404, f"Rule {rule_id} not found")
    before = _open_outcomes()
    rule = compliance.update_rule(rule_id, body.changes, user, body.note)
    return {"rule": rule, "rulebook_version": compliance.rulebook_version(), "impact": _impact(before, _open_outcomes())}


@router.post("/rules")
def create(body: RuleCreate, user=EDIT):
    before = _open_outcomes()
    rule = compliance.create_rule(body.rule, user, body.note)
    return {"rule": rule, "rulebook_version": compliance.rulebook_version(), "impact": _impact(before, _open_outcomes())}


@router.get("/export")
def export(user=VIEW):
    audit.log(user, "compliance.rules_exported", "rulebook", str(compliance.rulebook_version()))
    keep = ("rule_id", "name", "type", "clause_ref", "params", "severity", "blocking", "active", "description")
    return [{k: r.get(k) for k in keep} for r in compliance.list_rules()]


@router.post("/import")
def import_rules(body: RuleImport, user=EDIT):
    before = _open_outcomes()
    result = compliance.import_rules(body.rules, user)
    result["impact"] = _impact(before, _open_outcomes())
    return result


@router.get("/summary")
def summary(user=VIEW):
    reps = reports.list_reports()
    by_rule: dict[str, int] = {}
    for r in reps:
        for rid in r["blocking_failures"]:
            by_rule[rid] = by_rule.get(rid, 0) + 1
    names = {r["rule_id"]: r["name"] for r in compliance.list_rules()}
    return {"rulebook_version": compliance.rulebook_version(), "reports": len(reps),
            "approved": sum(1 for r in reps if r["status"] == "approved"),
            "blocked": sum(1 for r in reps if r["blocking_failures"] and r["status"] != "approved"),
            "avg_score": round(sum(r["compliance_score"] for r in reps) / len(reps), 1) if reps else None,
            "blocking_by_rule": [{"rule_id": k, "name": names.get(k, k), "reports": v}
                                 for k, v in sorted(by_rule.items(), key=lambda x: -x[1])]}
