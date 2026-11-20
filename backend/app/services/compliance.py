"""Compliance rule engine with an editable, versioned rulebook.

Rules are DATA (stored in SQLite, seeded from data/compliance_rules.json), not code. Each rule has a `type`
that maps to an evaluator function below; `params` tune it (e.g. hours: 24). Editing a rule creates a new
version and bumps the global rulebook version, so every report records which rulebook it was checked against.
"""
from __future__ import annotations

import json
from datetime import datetime

from app.core import audit, db
from app.core.config import DATA_DIR

SEVERITIES = ("minor", "major", "critical")
EDITABLE_FIELDS = {"name", "clause_ref", "description", "params", "severity", "blocking", "active"}


# ---------------------------------------------------------------- param validation per rule type
def _num(v, name, minimum=0):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < minimum:
        raise ValueError(f"'{name}' must be a number >= {minimum}")


def _validate_params(rtype: str, p: dict):
    if rtype not in EVALUATORS:
        raise ValueError(f"Unknown rule type '{rtype}'. Allowed: {', '.join(sorted(EVALUATORS))}")
    if rtype in ("deadline",):
        _num(p.get("hours"), "hours", 1)
    elif rtype == "critical_escalation":
        _num(p.get("hours"), "hours", 0.1)
    elif rtype == "traceability":
        if not isinstance(p.get("fields"), list) or not p["fields"]:
            raise ValueError("'fields' must be a non-empty list")
    elif rtype == "disposition_required":
        if not isinstance(p.get("allowed"), list) or not p["allowed"]:
            raise ValueError("'allowed' must be a non-empty list")
    elif rtype == "sampling_plan":
        t = p.get("table")
        if not isinstance(t, list) or not all(isinstance(r, list) and len(r) == 2 for r in t):
            raise ValueError("'table' must be a list of [max_lot_size, min_sample] pairs")
    elif rtype == "required_sections":
        if not isinstance(p.get("sections"), list):
            raise ValueError("'sections' must be a list")
    elif rtype == "cpk_threshold":
        _num(p.get("min_cpk"), "min_cpk", 0)
    elif rtype == "low_confidence_review":
        _num(p.get("threshold"), "threshold", 0)
        if p["threshold"] > 1:
            raise ValueError("'threshold' must be between 0 and 1")
    elif rtype == "material_cert":
        if not isinstance(p.get("allow_deviation", True), bool):
            raise ValueError("'allow_deviation' must be true or false")
    elif rtype == "threshold":
        _num(p.get("max"), "max", 0)
        if p.get("metric") not in ("defect_rate_pct", "critical_defects", "out_of_spec_parts"):
            raise ValueError("'metric' must be defect_rate_pct, critical_defects or out_of_spec_parts")


def validate_rule(rule: dict):
    for f in ("rule_id", "name", "type", "severity"):
        if not rule.get(f):
            raise ValueError(f"'{f}' is required")
    if rule["severity"] not in SEVERITIES:
        raise ValueError(f"'severity' must be one of {SEVERITIES}")
    if not isinstance(rule.get("params", {}), dict):
        raise ValueError("'params' must be an object")
    _validate_params(rule["type"], rule.get("params", {}))


# ---------------------------------------------------------------- storage
def rulebook_version() -> int:
    return int(db.get_meta("rulebook_version", "0"))


def seed_rules(path=None):
    rules = json.loads(((path or DATA_DIR / "compliance_rules.json")).read_text())
    if db.query_one("SELECT 1 FROM rule_versions LIMIT 1"):
        # existing rulebook: only add rules that are new in the synthetic rulebook (never overwrite edits)
        have = {r["rule_id"] for r in db.query("SELECT DISTINCT rule_id FROM rule_versions")}
        new = [r for r in rules if r["rule_id"] not in have]
        if new:
            book = rulebook_version() + 1
            with db.tx() as c:
                for r in new:
                    validate_rule(r)
                    c.execute("INSERT INTO rule_versions(rule_id, version, rulebook_version, changed_by, changed_at, "
                              "change_note, data) VALUES (?,?,?,?,?,?,?)",
                              (r["rule_id"], 1, book, "system", db.now_iso(), "Added to synthetic rulebook", db.dumps(r)))
            db.set_meta("rulebook_version", str(book))
        return
    with db.tx() as c:
        for r in rules:
            validate_rule(r)
            c.execute("INSERT INTO rule_versions(rule_id, version, rulebook_version, changed_by, changed_at, change_note, data) "
                      "VALUES (?,?,?,?,?,?,?)", (r["rule_id"], 1, 1, "system", db.now_iso(), "Initial synthetic rulebook",
                                                 db.dumps(r)))
    db.set_meta("rulebook_version", "1")


def list_rules(include_inactive: bool = True) -> list[dict]:
    rows = db.query("""SELECT rv.* FROM rule_versions rv
                       JOIN (SELECT rule_id, MAX(version) v FROM rule_versions GROUP BY rule_id) m
                         ON m.rule_id = rv.rule_id AND m.v = rv.version ORDER BY rv.rule_id""")
    out = []
    for r in rows:
        rule = db.loads(r["data"])
        rule.update({"version": r["version"], "changed_by": r["changed_by"], "changed_at": r["changed_at"]})
        if include_inactive or rule.get("active", True):
            out.append(rule)
    return out


def get_rule(rule_id: str) -> dict | None:
    return next((r for r in list_rules() if r["rule_id"] == rule_id), None)


def history(rule_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM rule_versions WHERE rule_id=? ORDER BY version DESC", (rule_id,))
    return [{"version": r["version"], "rulebook_version": r["rulebook_version"], "changed_by": r["changed_by"],
             "changed_at": r["changed_at"], "change_note": r["change_note"], "rule": db.loads(r["data"])} for r in rows]


def _save(rule: dict, version: int, user: dict, note: str) -> int:
    new_book = rulebook_version() + 1
    clean = {k: v for k, v in rule.items() if k not in ("version", "changed_by", "changed_at")}
    with db.tx() as c:
        c.execute("INSERT INTO rule_versions(rule_id, version, rulebook_version, changed_by, changed_at, change_note, data) "
                  "VALUES (?,?,?,?,?,?,?)", (rule["rule_id"], version, new_book, user["username"], db.now_iso(), note,
                                             db.dumps(clean)))
    db.set_meta("rulebook_version", str(new_book))
    return new_book


def update_rule(rule_id: str, changes: dict, user: dict, note: str = "") -> dict:
    current = get_rule(rule_id)
    if not current:
        raise KeyError(rule_id)
    bad = set(changes) - EDITABLE_FIELDS
    if bad:
        raise ValueError(f"These fields cannot be changed: {', '.join(sorted(bad))}")
    updated = {k: v for k, v in current.items() if k not in ("version", "changed_by", "changed_at")}
    updated.update(changes)
    validate_rule(updated)
    before = {k: current[k] for k in changes}
    if before == {k: updated[k] for k in changes}:
        return current
    book = _save(updated, current["version"] + 1, user, note or "Rule edited")
    audit.log(user, "compliance.rule_updated", "rule", rule_id, before=before, after=changes,
              meta={"rule_version": current["version"] + 1, "rulebook_version": book, "note": note})
    return get_rule(rule_id)


def create_rule(rule: dict, user: dict, note: str = "") -> dict:
    if get_rule(rule.get("rule_id", "")):
        raise ValueError(f"Rule {rule['rule_id']} already exists")
    rule = {"active": True, "blocking": False, "params": {}, "description": "", "clause_ref": "", **rule}
    validate_rule(rule)
    book = _save(rule, 1, user, note or "Rule created")
    audit.log(user, "compliance.rule_created", "rule", rule["rule_id"], after=rule, meta={"rulebook_version": book})
    return get_rule(rule["rule_id"])


def import_rules(rules: list[dict], user: dict) -> dict:
    created, updated = [], []
    for r in rules:
        validate_rule(r)
        if get_rule(r["rule_id"]):
            changes = {k: v for k, v in r.items() if k in EDITABLE_FIELDS}
            update_rule(r["rule_id"], changes, user, "Imported from JSON")
            updated.append(r["rule_id"])
        else:
            create_rule(r, user, "Imported from JSON")
            created.append(r["rule_id"])
    return {"created": created, "updated": updated, "rulebook_version": rulebook_version()}


# ---------------------------------------------------------------- evaluators
def _dt(v):
    return datetime.fromisoformat(str(v)) if v else None


def _res(result: str, reason: str):
    return result, reason


def ev_deadline(rule, rep, now):
    hours = float(rule["params"]["hours"])
    shift_end = _dt(rep["meta"]["shift_end"])
    submitted = _dt(rep["signoffs"].get("submitted_at"))
    ref = submitted or now
    elapsed = (ref - shift_end).total_seconds() / 3600
    if submitted:
        return _res("pass" if elapsed <= hours else "fail",
                    f"Submitted {elapsed:.1f} h after shift end (limit {hours:g} h).")
    if elapsed > hours:
        return _res("fail", f"Not submitted and {elapsed:.1f} h since shift end (limit {hours:g} h) - overdue.")
    return _res("warn", f"Not submitted yet - {hours - elapsed:.1f} h left of the {hours:g} h limit.")


def ev_traceability(rule, rep, now):
    fields = rule["params"]["fields"]
    missing = [d.get("id", "?") for d in rep["defects"] if any(not d.get(f) for f in fields)]
    if missing:
        return _res("fail", f"{len(missing)} defect(s) missing {', '.join(fields)}: {', '.join(missing[:5])}")
    return _res("pass", f"All {len(rep['defects'])} defects traceable to {' and '.join(fields)}.")


def ev_critical_escalation(rule, rep, now):
    crit = [d for d in rep["defects"] if d.get("severity") == "critical"]
    if not crit:
        return _res("na", "No critical defects in this report.")
    hours = float(rule["params"]["hours"])
    created = _dt(rep["meta"]["created_at"])
    esc = _dt(rep["signoffs"].get("escalated_at"))
    problems = []
    if not esc:
        waited = (now - created).total_seconds() / 3600
        if waited > hours:
            problems.append(f"not escalated ({waited:.1f} h since report, limit {hours:g} h)")
        else:
            problems.append(f"escalation pending ({hours - waited:.1f} h left)")
    elif (esc - created).total_seconds() / 3600 > hours:
        problems.append(f"escalated late ({(esc - created).total_seconds() / 3600:.1f} h)")
    if rule["params"].get("require_containment", True) and not any(
            a.strip() for a in rep["sections"].get("containment_actions", [])):
        problems.append("no containment action recorded")
    if not problems:
        return _res("pass", f"{len(crit)} critical defect(s) escalated in time with containment.")
    hard = [p for p in problems if not p.startswith("escalation pending")]
    return _res("fail" if hard else "warn", f"{len(crit)} critical defect(s): " + "; ".join(problems) + ".")


def ev_disposition(rule, rep, now):
    allowed = {a.lower() for a in rule["params"]["allowed"]}
    items = rep["out_of_spec"]
    if not items:
        return _res("na", "No out-of-spec measurements.")
    missing = [f"{i['part_serial']} {i['feature']}" for i in items if (i.get("disposition") or "").lower() not in allowed]
    if missing:
        return _res("fail", f"{len(missing)} of {len(items)} out-of-spec item(s) have no valid disposition: "
                            + ", ".join(missing[:4]))
    return _res("pass", f"All {len(items)} out-of-spec items have a disposition.")


def ev_calibration(rule, rep, now):
    insp_date = _dt(rep["meta"]["shift_end"]).date()
    bad = [f"{g['gauge_id']} (due {g['calibration_due']})" for g in rep["meta"].get("gauges", [])
           if datetime.fromisoformat(g["calibration_due"]).date() < insp_date]
    if bad:
        return _res("fail", "Gauge calibration expired on inspection date: " + ", ".join(bad))
    return _res("pass", f"All {len(rep['meta'].get('gauges', []))} gauges within calibration.")


def ev_sampling(rule, rep, now):
    lot_size, sampled = int(rep["meta"]["lot_size"]), int(rep["meta"]["sampled"])
    required = next((int(s) for mx, s in sorted(rule["params"]["table"]) if lot_size <= mx), None)
    if required is None:
        return _res("warn", f"Lot size {lot_size} is larger than the sampling table covers.")
    if sampled >= required:
        return _res("pass", f"Sampled {sampled} parts; plan requires {required} for lot size {lot_size}.")
    return _res("fail", f"Sampled {sampled} parts; plan requires {required} for lot size {lot_size}.")


def ev_approval(rule, rep, now):
    s = rep["signoffs"]
    from app.services.reports import risk_reasons  # local import: reports imports this module
    reasons = risk_reasons(rep)
    if reasons and s.get("approved_by") and not s.get("released_by"):
        return _res("warn", f"Approved by {s['approved_by']}; high-risk ({'; '.join(reasons)}) - awaiting Plant "
                            "Quality Head release.")
    if reasons and s.get("released_by"):
        return _res("pass", f"Reviewed by {s['reviewed_by']}, approved by {s['approved_by']}, released by "
                            f"{s['released_by']} (high-risk).")
    if s.get("approved_by") and s.get("reviewed_by"):
        return _res("pass", f"Reviewed by {s['reviewed_by']}, approved by {s['approved_by']}.")
    if s.get("reviewed_by"):
        return _res("warn", f"Reviewed by {s['reviewed_by']}; awaiting quality manager approval.")
    return _res("warn", "Awaiting supervisor review and quality manager approval.")


def ev_required_sections(rule, rep, now):
    nothing_found = not rep["defects"] and not rep["out_of_spec"]
    missing = [s for s in rule["params"]["sections"] if not rep["sections"].get(s)
               and not (s == "defect_descriptions" and nothing_found)]
    if missing:
        return _res("fail", "Empty mandatory section(s): " + ", ".join(missing))
    return _res("pass", "All mandatory sections are filled in.")


def ev_cpk(rule, rep, now):
    mn = float(rule["params"]["min_cpk"])
    low = [f"{f['feature']} (Cpk {f['cpk']})" for f in rep["features"] if f.get("cpk") is not None and f["cpk"] < mn]
    if not low:
        return _res("pass", f"All features have Cpk >= {mn}.")
    if rep["sections"].get("recommended_actions"):
        return _res("warn", f"Cpk below {mn}: {', '.join(low)}. Action plan present - track to closure.")
    return _res("fail", f"Cpk below {mn}: {', '.join(low)} and no recommended action recorded.")


def ev_ai_advisory(rule, rep, now):
    banned = [b.lower() for b in rule["params"].get("banned_generic", [])]
    causes = rep["sections"].get("root_causes", [])
    if not causes:
        return _res("warn", "No root-cause hypotheses recorded.")
    generic = [c.get("hypothesis", "") for c in causes if any(b in c.get("hypothesis", "").lower() for b in banned)
               or len(c.get("hypothesis", "").split()) < 4]
    if generic:
        return _res("warn", "Advisory: root cause looks generic - add specific evidence: " + "; ".join(generic[:3]))
    return _res("pass", f"{len(causes)} specific, evidence-linked root-cause hypotheses.")


def ev_low_conf(rule, rep, now):
    th = float(rule["params"]["threshold"])
    pending = [d for d in rep["defects"] if float(d.get("confidence", 1)) < th and not d.get("verified")]
    total = sum(1 for d in rep["defects"] if float(d.get("confidence", 1)) < th)
    if not total:
        return _res("na", f"No detections below {th:.0%} confidence.")
    if pending:
        return _res("fail", f"{len(pending)} of {total} low-confidence detection(s) not yet verified by a person.")
    return _res("pass", f"All {total} low-confidence detections verified by a person.")


def ev_threshold(rule, rep, now):
    metric, mx = rule["params"]["metric"], float(rule["params"]["max"])
    val = float(rep["kpis"].get(metric, 0))
    return _res("pass" if val <= mx else "warn", f"{metric} = {val:g} (target <= {mx:g}).")


def ev_material_cert(rule, rep, now):
    m = rep.get("material")
    if not m:
        return _res("na", "No raw-material lot linked to this production lot.")
    label = f"{m['material_lot']} (heat {m['heat_number']}, {m['supplier']})"
    if not m.get("deviations"):
        return _res("pass", f"Material {label} meets its certificate spec.")
    devs = "; ".join(m["deviations"])
    if m.get("deviation_ref") and rule["params"].get("allow_deviation", True):
        return _res("warn", f"Material {label} outside spec ({devs}) - used under deviation {m['deviation_ref']}.")
    return _res("fail", f"Material {label} outside spec ({devs}) with no approved deviation.")


EVALUATORS = {
    "deadline": ev_deadline, "traceability": ev_traceability, "critical_escalation": ev_critical_escalation,
    "disposition_required": ev_disposition, "calibration_valid": ev_calibration, "sampling_plan": ev_sampling,
    "approval": ev_approval, "required_sections": ev_required_sections, "cpk_threshold": ev_cpk,
    "ai_advisory": ev_ai_advisory, "low_confidence_review": ev_low_conf, "threshold": ev_threshold,
    "material_cert": ev_material_cert,
}


def evaluate(report: dict, rules: list[dict] | None = None, now: datetime | None = None) -> dict:
    rules = rules if rules is not None else list_rules(include_inactive=False)
    now = now or datetime.now()
    results = []
    for rule in rules:
        if not rule.get("active", True):
            continue
        try:
            result, reason = EVALUATORS[rule["type"]](rule, report, now)
        except Exception as e:  # a broken rule must never crash report handling
            result, reason = "warn", f"Rule could not be evaluated: {e}"
        results.append({"rule_id": rule["rule_id"], "name": rule["name"], "severity": rule["severity"],
                        "blocking": bool(rule.get("blocking")), "type": rule["type"],
                        "advisory": rule["type"] == "ai_advisory", "rule_version": rule.get("version", 1),
                        "result": result, "reason": reason})
    scored = [r for r in results if r["result"] != "na"]
    passed = sum(1 for r in scored if r["result"] == "pass")
    blocking = [r for r in results if r["blocking"] and r["result"] == "fail"]
    return {"rulebook_version": rulebook_version(), "evaluated_at": now.replace(microsecond=0).isoformat(),
            "score_pct": round(100 * passed / len(scored), 1) if scored else 100.0,
            "passed": passed, "failed": sum(1 for r in scored if r["result"] == "fail"),
            "warnings": sum(1 for r in scored if r["result"] == "warn"),
            "blocking_failures": [r["rule_id"] for r in blocking], "can_approve": not blocking, "results": results}
