"""Report storage, editing (versioned + audited) and the approval workflow."""
from __future__ import annotations

import copy
from datetime import datetime

from app.core import audit, db
from app.services import compliance

STATUSES = ("draft", "in_review", "reviewed", "awaiting_release", "approved")
EDITABLE_SECTIONS = {"purpose", "executive_summary", "defect_descriptions", "measurement_analysis", "root_causes",
                     "recommended_actions", "containment_actions"}
DISPOSITIONS = ("", "scrap", "rework", "hold", "use-as-is (deviation)")


class WorkflowError(Exception):
    pass


# Who is responsible for each step, in order. Each sign-off must be done by a different person
# (segregation of duties): the reviewer cannot be the submitter, the approver cannot be the submitter or reviewer.
APPROVAL_CHAIN = [
    {"key": "prepare", "step": "Prepare & submit", "role": "Inspector",
     "duty": "Checks the AI draft against the parts, verifies low-confidence detections, sets dispositions, submits."},
    {"key": "review", "step": "Technical review", "role": "Line Supervisor",
     "duty": "Confirms findings, root causes and actions are correct for the line; requests changes if not."},
    {"key": "approve", "step": "Approval & lot release", "role": "Quality Manager",
     "duty": "Final decision to release, hold or reject the lot. Blocked while any blocking compliance rule fails."},
]
RELEASE_STEP = {"key": "release", "step": "High-risk release", "role": "Plant Quality Head",
                "duty": "Second, independent sign-off required because this report is high-risk."}


def risk_reasons(rep: dict) -> list[str]:
    """Why a report needs the Plant Quality Head release on top of the Quality Manager approval."""
    reasons = []
    crit = sum(1 for d in rep.get("defects", []) if d.get("severity") == "critical")
    if crit:
        reasons.append(f"{crit} critical defect(s)")
    m = rep.get("material") or {}
    if m.get("deviations"):
        reasons.append(f"raw material {m['material_lot']} outside certificate spec")
    uai = sum(1 for o in rep.get("out_of_spec", []) if o.get("disposition") == "use-as-is (deviation)")
    if uai:
        reasons.append(f"{uai} part(s) dispositioned use-as-is under deviation")
    return reasons
ESCALATION_STEP = {"key": "escalate", "step": "Critical-defect escalation", "role": "Inspector / Supervisor -> Quality Manager",
                   "duty": "Critical defects must be escalated within the R-003 time limit with a containment action."}


def approval_chain(rep: dict) -> list[dict]:
    s, status = rep["signoffs"], rep["status"]
    done = {"prepare": bool(s.get("submitted_by")), "review": bool(s.get("reviewed_by")),
            "approve": bool(s.get("approved_by")), "release": bool(s.get("released_by"))}
    by = {"prepare": (s.get("submitted_by"), s.get("submitted_at")), "review": (s.get("reviewed_by"), s.get("reviewed_at")),
          "approve": (s.get("approved_by"), s.get("approved_at")), "release": (s.get("released_by"), s.get("released_at"))}
    nxt = {"draft": "prepare", "in_review": "review", "reviewed": "approve", "awaiting_release": "release"}.get(status)
    reasons = risk_reasons(rep)
    steps = list(APPROVAL_CHAIN)
    if reasons or s.get("released_by"):
        steps.append({**RELEASE_STEP, "duty": RELEASE_STEP["duty"] + " Reason: " + ("; ".join(reasons) or "high-risk") + "."})
    out = []
    for st in steps:
        who, at = by[st["key"]]
        out.append({**st, "signed_by": who or "", "signed_at": at or "",
                    "state": "done" if done[st["key"]] else "current" if st["key"] == nxt else "pending"})
    if any(d.get("severity") == "critical" for d in rep.get("defects", [])):
        out.insert(1, {**ESCALATION_STEP, "signed_by": s.get("escalated_by", ""), "signed_at": s.get("escalated_at", ""),
                       "state": "done" if s.get("escalated_at") else "current"})
    return out


def _check_separation(action: str, rep: dict, user: dict):
    s, me = rep["signoffs"], user["username"]
    if action == "review" and me == s.get("submitted_by"):
        raise WorkflowError("Segregation of duties: you submitted this report, so a different supervisor must review it.")
    if action == "approve" and me in (s.get("submitted_by"), s.get("reviewed_by")):
        raise WorkflowError("Segregation of duties: you already signed this report (submitted or reviewed), "
                            "so a different quality manager must approve it.")
    if action == "release" and me in (s.get("submitted_by"), s.get("reviewed_by"), s.get("approved_by")):
        raise WorkflowError("Segregation of duties: you already signed this report, so a different "
                            "Plant Quality Head must release it.")


def _new_id(line: str) -> str:
    n = db.query_one("SELECT COUNT(*) AS n FROM reports")["n"] + 1
    return f"RPT-{datetime.now():%y%m%d}-{line}-{n:03d}"


def save_new(report: dict, user: dict) -> dict:
    rid = _new_id(report["meta"]["line"])
    report["id"], report["status"], report["version"] = rid, "draft", 1
    now = db.now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO reports(id, line, lot, shift, status, created_by, created_at, updated_at, data) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (rid, report["meta"]["line"], report["meta"]["lot"],
                                                 report["meta"]["shift"], "draft", user["username"], now, now,
                                                 db.dumps(report)))
        c.execute("INSERT INTO report_versions(report_id, version, changed_by, changed_at, change_note, data) "
                  "VALUES (?,?,?,?,?,?)", (rid, 1, user["username"], now, "Generated", db.dumps(report)))
    audit.log(user, "report.generated", "report", rid,
              meta={"lot": report["meta"]["lot"], "ai_mode": report["ai"]["mode"],
                    "seconds": report["ai"]["generation_seconds"],
                    "guardrails": {x["check"]: x["status"] for x in report["guardrails"]}})
    return report


def get(rid: str, with_compliance: bool = True) -> dict | None:
    row = db.query_one("SELECT * FROM reports WHERE id=?", (rid,))
    if not row:
        return None
    rep = db.loads(row["data"])
    if not rep["sections"].get("purpose"):  # reports created before the purpose section existed
        from app.services.report_builder import purpose_text
        rep["sections"]["purpose"] = purpose_text(rep["meta"], rep.get("features", []), rep.get("material"))
    rep["approval_chain"] = approval_chain(rep)
    if with_compliance:
        rep["compliance"] = rep.get("compliance_snapshot") if rep["status"] == "approved" else compliance.evaluate(rep)
    return rep


def list_reports(status: str = "", line: str = "") -> list[dict]:
    sql, p = "SELECT * FROM reports WHERE 1=1", []
    if status:
        sql += " AND status=?"
        p.append(status)
    if line:
        sql += " AND line=?"
        p.append(line)
    out = []
    for row in db.query(sql + " ORDER BY created_at DESC", tuple(p)):
        rep = db.loads(row["data"])
        comp = rep.get("compliance_snapshot") if rep["status"] == "approved" else compliance.evaluate(rep)
        out.append({"id": rep["id"], "status": rep["status"], "version": rep["version"], "lot": rep["meta"]["lot"],
                    "line": rep["meta"]["line"], "part": rep["meta"]["part"], "shift": rep["meta"]["shift"],
                    "shift_end": rep["meta"]["shift_end"], "created_at": rep["meta"]["created_at"],
                    "created_by": rep["meta"]["created_by"], "defect_rate_pct": rep["kpis"]["defect_rate_pct"],
                    "critical_defects": rep["kpis"]["critical_defects"], "ai_mode": rep["ai"]["mode"],
                    "compliance_score": comp["score_pct"], "blocking_failures": comp["blocking_failures"],
                    "guardrail_warnings": sum(1 for x in rep["guardrails"] if x["status"] != "pass")})
    return out


def _store(rep: dict, user: dict, note: str):
    rep["version"] += 1
    now = db.now_iso()
    clean = {k: v for k, v in rep.items() if k not in ("compliance", "approval_chain")}
    with db.tx() as c:
        c.execute("UPDATE reports SET status=?, updated_at=?, data=? WHERE id=?",
                  (rep["status"], now, db.dumps(clean), rep["id"]))
        c.execute("INSERT INTO report_versions(report_id, version, changed_by, changed_at, change_note, data) "
                  "VALUES (?,?,?,?,?,?)", (rep["id"], rep["version"], user["username"], now, note, db.dumps(clean)))


def versions(rid: str) -> list[dict]:
    return [{"version": r["version"], "changed_by": r["changed_by"], "changed_at": r["changed_at"],
             "change_note": r["change_note"]}
            for r in db.query("SELECT version, changed_by, changed_at, change_note FROM report_versions "
                              "WHERE report_id=? ORDER BY version DESC", (rid,))]


def update(rid: str, patch: dict, user: dict) -> dict:
    """patch keys: sections{...}, dispositions{index: value}, verify[defect ids], note."""
    rep = get(rid, with_compliance=False)
    if not rep:
        raise KeyError(rid)
    if rep["status"] == "approved":
        raise WorkflowError("Approved reports are locked and cannot be edited.")
    if rep["status"] == "awaiting_release":
        raise WorkflowError("Report is waiting for Plant Quality Head release; it must be sent back before editing.")
    if rep["status"] == "reviewed" and user["role"] == "inspector":
        raise WorkflowError("Report is under review; ask the supervisor to request changes first.")
    before, after = {}, {}

    for key, value in (patch.get("sections") or {}).items():
        if key not in EDITABLE_SECTIONS:
            raise ValueError(f"Section '{key}' cannot be edited.")
        if rep["sections"].get(key) != value:
            before[f"sections.{key}"] = copy.deepcopy(rep["sections"].get(key))
            after[f"sections.{key}"] = value
            rep["sections"][key] = value

    for idx, disp in (patch.get("dispositions") or {}).items():
        i = int(idx)
        if disp not in DISPOSITIONS:
            raise ValueError(f"Disposition must be one of: {', '.join(d for d in DISPOSITIONS if d)}")
        item = rep["out_of_spec"][i]
        if item.get("disposition") != disp:
            before[f"disposition.{item['part_serial']}.{item['feature']}"] = item.get("disposition")
            after[f"disposition.{item['part_serial']}.{item['feature']}"] = disp
            item["disposition"] = disp

    for did in patch.get("verify") or []:
        d = next((x for x in rep["defects"] if x["id"] == did), None)
        if d and not d["verified"]:
            d.update(verified=True, verified_by=user["username"], verified_at=db.now_iso())
            before[f"verified.{did}"], after[f"verified.{did}"] = False, True

    if not after:
        return get(rid)
    rep["edited_by_human"] = True
    _store(rep, user, patch.get("note") or "Edited")
    audit.log(user, "report.edited", "report", rid, before=before, after=after, meta={"version": rep["version"]})
    return get(rid)


# ---------------------------------------------------------------- workflow
def transition(rid: str, action: str, user: dict, comment: str = "") -> dict:
    rep = get(rid, with_compliance=False)
    if not rep:
        raise KeyError(rid)
    s, now = rep["signoffs"], db.now_iso()
    status = rep["status"]
    _check_separation(action, rep, user)

    if action == "submit":
        if status != "draft":
            raise WorkflowError(f"Only draft reports can be submitted (current: {status}).")
        rep["status"] = "in_review"
        s.update(submitted_by=user["username"], submitted_at=now)
    elif action == "review":
        if status != "in_review":
            raise WorkflowError(f"Only reports in review can be marked reviewed (current: {status}).")
        rep["status"] = "reviewed"
        s.update(reviewed_by=user["username"], reviewed_at=now)
    elif action == "request_changes":
        if status not in ("in_review", "reviewed"):
            raise WorkflowError(f"Changes can only be requested during review (current: {status}).")
        if not comment.strip():
            raise WorkflowError("Please add a comment explaining the changes needed.")
        rep["status"] = "draft"
        s.update(reviewed_by="", reviewed_at="")
    elif action == "approve":
        if status != "reviewed":
            raise WorkflowError(f"Only reviewed reports can be approved (current: {status}).")
        s.update(approved_by=user["username"], approved_at=now)
        result = compliance.evaluate(rep)
        if not result["can_approve"]:
            s.update(approved_by="", approved_at="")
            audit.log(user, "report.approval_blocked", "report", rid,
                      meta={"blocking_failures": result["blocking_failures"]})
            raise WorkflowError("Approval blocked by compliance rule(s): " + ", ".join(
                f"{r['rule_id']} {r['name']}" for r in result["results"] if r["rule_id"] in result["blocking_failures"]))
        reasons = risk_reasons(rep)
        if reasons:  # high-risk: Quality Manager approval alone is not enough
            rep["status"] = "awaiting_release"
            rep["ai"]["label"] = f"Approved by {user['name']} - awaiting Plant Quality Head release"
        else:
            rep["status"] = "approved"
            rep["compliance_snapshot"] = result
            rep["ai"]["label"] = f"AI-assisted report - approved by {user['name']}"
    elif action == "release":
        if status != "awaiting_release":
            raise WorkflowError(f"Only reports awaiting release can be released (current: {status}).")
        if not compliance.evaluate(rep)["can_approve"]:
            raise WorkflowError("Release blocked: a blocking compliance rule is failing.")
        s.update(released_by=user["username"], released_at=now)
        rep["status"] = "approved"
        rep["compliance_snapshot"] = compliance.evaluate(rep)
        rep["ai"]["label"] = f"AI-assisted report - approved, released by {user['name']} (high-risk)"
    elif action == "send_back":
        if status != "awaiting_release":
            raise WorkflowError(f"Only reports awaiting release can be sent back (current: {status}).")
        if not comment.strip():
            raise WorkflowError("Please add a comment explaining why the report is sent back.")
        rep["status"] = "draft"
        s.update(submitted_by="", submitted_at="", reviewed_by="", reviewed_at="", approved_by="", approved_at="")
    elif action == "escalate":
        if s.get("escalated_at"):
            raise WorkflowError("Already escalated.")
        s.update(escalated_at=now, escalated_by=user["username"])
    else:
        raise WorkflowError(f"Unknown action '{action}'.")

    if comment.strip():
        s["comments"].append({"by": user["username"], "role": user["role"], "at": now, "action": action,
                              "text": comment.strip()[:1000]})
    _store(rep, user, f"Workflow: {action}")
    audit.log(user, f"report.{action}", "report", rid, before={"status": status}, after={"status": rep["status"]},
              meta={"comment": comment[:200]} if comment else None)
    return get(rid)

