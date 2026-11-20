"""Report generation: facts (code) -> input guardrails -> LLM (words) -> output guardrails -> standardized report.

If the LLM is not configured (mock mode) or fails, a deterministic template writes the sections from the same
facts, so a report is ALWAYS produced (graceful degradation).
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core import config, guardrails as g, prompts
from app.services import ai, analytics
from app.services.inspection_source import SyntheticSource

LOW_CONF = 0.7
MANUAL_BASELINE_MIN = 120  # assumption shown in the UI: typical manual effort to compile one report


# ---------------------------------------------------------------- expected LLM output (schema guardrail)
class DefectDescription(BaseModel):
    defect_code: str
    title: str = ""
    description: str = ""
    severity: str = "minor"
    evidence: list[str] = Field(default_factory=list)


class RootCause(BaseModel):
    hypothesis: str
    evidence: str = ""
    confidence: Literal["low", "medium", "high"] = "low"


class Action(BaseModel):
    action: str
    owner_role: str = "Quality Manager"
    priority: Literal["high", "medium", "low"] = "medium"


class LLMReport(BaseModel):
    executive_summary: str
    defect_descriptions: list[DefectDescription] = Field(default_factory=list)
    measurement_analysis: str = ""
    root_causes: list[RootCause] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)
    containment_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- facts (all numbers come from here)
def collect(store: SyntheticSource, lot: str) -> dict:
    lots = store.lots()
    row = lots[lots.lot == lot]
    if row.empty:
        raise KeyError(f"Lot {lot} not found")
    lr = row.iloc[0]
    meas = store.measurements()
    meas = meas[meas.lot == lot]
    det = store.detections()
    det = det[det.lot == lot].sort_values("ts")
    checks = store.manual_checks()
    checks = checks[checks.lot == lot]
    line = store.line(lr.line)
    codes = store.defect_codes()
    code_names = {c["code"]: c["name"] for c in codes}

    defects = []
    for i, d in enumerate(det.itertuples(), start=1):
        defects.append({"id": f"DEF-{i:03d}", "part_serial": d.part_serial, "lot": d.lot, "station": d.station,
                        "camera_id": d.camera_id, "ts": d.ts.isoformat(timespec="minutes"),
                        "defect_code": d.defect_code, "defect_name": code_names.get(d.defect_code, d.defect_code),
                        "camera_label": d.defect_type, "severity": d.severity, "confidence": float(d.confidence),
                        "location": d.location, "image_id": d.image_id or "",
                        "needs_verification": float(d.confidence) < LOW_CONF, "verified": False, "verified_by": ""})

    oos = [{"part_serial": m.part_serial, "feature": m.feature, "value": float(m.value), "lsl": float(m.lsl),
            "usl": float(m.usl), "unit": m.unit, "station": m.station, "gauge_id": m.gauge_id,
            "suggested_disposition": "hold", "disposition": ""}
           for m in meas[~meas.in_spec.astype(bool)].itertuples()]

    gauges_used = sorted(set(meas.gauge_id))
    gauges = [dict(gg) for gg in store.gauges() if gg["gauge_id"] in gauges_used]
    material = store.material(lr.get("material_lot"))
    # line-level patterns that apply to this lot (a shift spike only to that shift, a material link only to that heat)
    insights = [i for i in analytics.detect_patterns(store)
                if i.get("line") == lr.line and (i["type"] != "shift_spike" or i.get("shift") == lr["shift"])
                and (i["type"] != "material" or (material and i.get("material_lot") == material["material_lot"]))]
    maint = store.maintenance()
    maint = maint[(maint.line == lr.line) & (maint.ts <= lr.shift_end)].tail(3)

    return {
        "lot_row": lr, "line": line, "codes": codes, "defects": defects, "out_of_spec": oos,
        "features": analytics.feature_stats(meas), "kpis": analytics.kpis(meas, det),
        "pareto": analytics.pareto(det, codes), "gauges": gauges, "insights": insights,
        "maintenance": [{"ts": m.ts.isoformat(timespec="minutes"), "station": m.station, "event": m.event}
                        for m in maint.itertuples()],
        "checks": checks, "material": material,
    }


def _people_map(store: SyntheticSource, checks) -> dict[str, str]:
    return {r.inspector_name: r.inspector_id for r in checks.drop_duplicates("inspector_id").itertuples()}


def build_notes(store, checks, codes) -> tuple[list[dict], dict]:
    """Sanitize + mask inspector notes and map messy wording to standard codes (input guardrails)."""
    people = _people_map(store, checks)
    findings, removed, masked = [], [], []
    for r in checks.itertuples():
        note = r.notes or ""
        if not note.strip() or note.strip().lower() in ("ok", "all good", "no issues"):
            continue
        clean, inj = g.sanitize_untrusted(note)
        clean, pii = g.mask_pii(clean, people)
        removed += inj
        masked += pii
        findings.append({"item": r.item, "result": r.result, "inspector_id": r.inspector_id,
                         "note": clean, "original_note_hidden": bool(inj or pii),
                         "standard_code": g.normalize_term(clean, codes)})
    stats = {"injections_removed": removed, "pii_masked": masked}
    return findings, stats


def llm_facts(c: dict) -> dict:
    """Compact facts object sent to the LLM (and used to verify the numbers it writes)."""
    lr = c["lot_row"]
    groups = {}
    for d in c["defects"]:
        gp = groups.setdefault(d["defect_code"], {"defect_code": d["defect_code"], "name": d["defect_name"],
                                                  "count": 0, "severities": set(), "locations": {},
                                                  "part_serials": [], "low_confidence": 0, "stations": set()})
        gp["count"] += 1
        gp["severities"].add(d["severity"])
        gp["locations"][d["location"]] = gp["locations"].get(d["location"], 0) + 1
        gp["stations"].add(d["station"])
        if len(gp["part_serials"]) < 8:
            gp["part_serials"].append(d["part_serial"])
        gp["low_confidence"] += int(d["needs_verification"])
    if c["out_of_spec"]:  # dimensional nonconformities are defects too (code D-DIM)
        oos = c["out_of_spec"]
        groups["D-DIM"] = {"defect_code": "D-DIM", "name": "Dimensional out-of-tolerance", "count": len(oos),
                           "severities": {"major"}, "locations": {o["feature"]: 1 for o in oos},
                           "part_serials": [o["part_serial"] for o in oos[:8]], "low_confidence": 0,
                           "stations": {o["station"] for o in oos}}
    for gp in groups.values():
        gp["severities"], gp["stations"] = sorted(gp["severities"]), sorted(gp["stations"])
    return {
        "lot": lr.lot, "line": lr.line, "part": c["line"]["part"], "shift": lr["shift"],
        "shift_window": f"{lr.shift_start:%Y-%m-%d %H:%M} to {lr.shift_end:%Y-%m-%d %H:%M}",
        "lot_size": int(lr.lot_size), "sampled": int(lr.sampled), "kpis": c["kpis"],
        "targets": {"min_cpk": 1.33, "low_confidence_threshold_pct": 70},
        "defect_groups": list(groups.values()),
        "features": [{k: f[k] for k in ("feature", "unit", "n", "mean", "std", "min", "max", "lsl", "usl", "cpk",
                                        "out_of_spec", "station")} for f in c["features"]],
        "out_of_spec": [{k: o[k] for k in ("part_serial", "feature", "value", "lsl", "usl", "unit")}
                        for o in c["out_of_spec"][:15]],
        "gauges": [{"gauge_id": x["gauge_id"], "calibration_due": x["calibration_due"]} for x in c["gauges"]],
        "line_insights": [{"title": i["title"], "detail": i["detail"], "metrics": i["metrics"],
                           "possible_cause": i.get("possible_cause")} for i in c["insights"]],
        "recent_maintenance": c["maintenance"],
        "raw_material": ({k: m[k] for k in ("material_lot", "material", "supplier", "heat_number", "received",
                                            "incoming_result", "deviation_ref", "deviations")}
                         | {"certificate": [{k: x[k] for k in ("property", "value", "min", "max", "in_spec")}
                                            for x in m["certificate"]]}) if (m := c.get("material")) else None,
    }


# ---------------------------------------------------------------- template writer (mock mode + fallback)
def template_sections(f: dict, findings: list[dict]) -> dict:
    k = f["kpis"]
    groups = sorted(f["defect_groups"], key=lambda x: -x["count"])
    top = ", ".join(f"{gp['name']} ({gp['count']})" for gp in groups[:3]) or "none"
    low_cpk = [x for x in f["features"] if x["cpk"] is not None and x["cpk"] < 1.33]
    summary = (f"Lot {f['lot']} ({f['part']}, line {f['line']}, shift {f['shift']}): {k['parts_inspected']} parts "
               f"inspected, {k['defective_parts']} defective ({k['defect_rate_pct']}%), first-pass yield "
               f"{k['first_pass_yield_pct']}%. Camera detections: {k['camera_detections']}; main defect types: {top}.")
    if k["critical_defects"]:
        summary += f" {k['critical_defects']} critical defect(s) require escalation and containment."
    if low_cpk:
        summary += " Capability below target on " + ", ".join(f"{x['feature']} (Cpk {x['cpk']})" for x in low_cpk) + "."
    if f["line_insights"]:
        summary += " Line-level pattern detected: " + f["line_insights"][0]["title"] + "."
    rm = f.get("raw_material")
    if rm and rm["deviations"]:
        summary += (f" Raw material {rm['material_lot']} (heat {rm['heat_number']}, {rm['supplier']}) is outside the "
                    f"certificate spec: {'; '.join(rm['deviations'])}.")

    descs = []
    for gp in groups:
        locs = ", ".join(sorted(gp["locations"], key=lambda x: -gp["locations"][x])[:2])
        sev = "critical" if "critical" in gp["severities"] else "major" if "major" in gp["severities"] else "minor"
        if gp["defect_code"] == "D-DIM":
            text = (f"{gp['count']} measurement(s) outside specification at {', '.join(gp['stations'])} "
                    f"on: {locs}. Parts are held pending disposition.")
        else:
            text = (f"{gp['count']} part(s) with {gp['name'].lower()} detected by camera at "
                    f"{', '.join(gp['stations'])}, mainly on {locs}.")
        if gp["low_confidence"]:
            text += f" {gp['low_confidence']} detection(s) have low confidence and need visual verification."
        descs.append({"defect_code": gp["defect_code"], "title": gp["name"], "description": text, "severity": sev,
                      "evidence": gp["part_serials"][:5]})

    if low_cpk or f["out_of_spec"]:
        meas = ("Capability below 1.33: " + ", ".join(f"{x['feature']} Cpk {x['cpk']} (mean {x['mean']} {x['unit']}, "
                                                      f"limits {x['lsl']}-{x['usl']})" for x in low_cpk) + ". "
                if low_cpk else "")
        meas += f"{len(f['out_of_spec'])} out-of-spec measurement(s) recorded." if f["out_of_spec"] else ""
    else:
        meas = "All measured features are within specification with Cpk at or above 1.33."

    causes = []
    for ins in f["line_insights"][:3]:
        causes.append({"hypothesis": ins["possible_cause"] or ins["title"], "evidence": ins["detail"],
                       "confidence": "medium"})
    actions = []
    for ins in f["line_insights"][:3]:
        if "raw-material" in ins["title"].lower():
            actions.append({"action": f"Quarantine remaining stock of {rm['material_lot'] if rm else 'the affected heat'} "
                                      "and raise a supplier corrective action request with the certificate and pitting data.",
                            "owner_role": "Quality Manager", "priority": "high"})
        elif "porosity" in ins["title"].lower() or "spike" in ins["title"].lower():
            actions.append({"action": "Inspect the replaced mold insert and verify casting parameters on the affected shift.",
                            "owner_role": "Maintenance", "priority": "high"})
        elif "drift" in ins["title"].lower():
            actions.append({"action": "Check grinding wheel / tool wear and re-centre the process before parts reach the limit.",
                            "owner_role": "Line Supervisor", "priority": "high"})
        elif "calibration" in ins["title"].lower():
            actions.append({"action": "Calibrate the expired gauge and re-verify parts measured with it.",
                            "owner_role": "Quality Manager", "priority": "high"})
    if low_cpk and not actions:
        actions.append({"action": "Start a capability improvement review for features with Cpk below 1.33.",
                        "owner_role": "Quality Manager", "priority": "medium"})
    contain = []
    if k["critical_defects"]:
        contain.append("Quarantine the lot and 100% inspect remaining parts for the critical defect type.")
    if f["out_of_spec"]:
        contain.append("Place out-of-spec parts on hold pending disposition.")
    if rm and rm["deviations"]:
        contain.append(f"Segregate parts made from material lot {rm['material_lot']} and stop issuing that heat to the line.")
    return {"executive_summary": summary, "defect_descriptions": descs, "measurement_analysis": meas,
            "root_causes": causes, "recommended_actions": actions, "containment_actions": contain}


# ---------------------------------------------------------------- purpose & scope (deterministic, editable)
def purpose_text(meta: dict, features: list[dict], material: dict | None) -> str:
    feats = ", ".join(sorted({f["feature"].replace("_", " ") for f in features})) or "the specified characteristics"
    stations = ", ".join(sorted({f["station"] for f in features})) or "line stations"
    gauges = ", ".join(g["gauge_id"] for g in meta.get("gauges", [])) or "the assigned gauges"
    mat = (f" made from raw-material lot {material['material_lot']} (heat {material['heat_number']}, "
           f"{material['supplier']})" if material else "")
    return (
        f"Purpose: to record the results of the shift {meta['shift']} inspection of lot {meta['lot']} "
        f"({meta['part']}, {meta['line_name']}) against the drawing and specification limits, so that the lot can be "
        "released, held or rejected on documented evidence. The report records every nonconformity with its "
        "disposition, root-cause hypotheses and corrective / containment actions, gives traceability to part serial, "
        "lot, raw material and gauge, and holds the review and approval sign-offs required before release.\n\n"
        f"Scope: {meta['sampled']} parts sampled from a lot of {meta['lot_size']}{mat}, inspected between "
        f"{meta['shift_start'][:16].replace('T', ' ')} and {meta['shift_end'][:16].replace('T', ' ')}. "
        f"Characteristics: {feats} (stations {stations}; gauges {gauges}), plus camera visual inspection at ST3 "
        f"and the shift manual checklist. Template {meta.get('template', 'QIR-STD-01')}.")


# ---------------------------------------------------------------- output guardrails
def _all_text(sections: dict) -> str:
    parts = [sections.get("executive_summary", ""), sections.get("measurement_analysis", "")]
    for d in sections.get("defect_descriptions", []):
        parts += [d.get("title", ""), d.get("description", "")]
    for r in sections.get("root_causes", []):
        parts += [r.get("hypothesis", ""), r.get("evidence", "")]
    parts += [a.get("action", "") for a in sections.get("recommended_actions", [])]
    parts += sections.get("containment_actions", [])
    return "\n".join(p for p in parts if p)


def _scrub(sections: dict) -> list[str]:
    hits = []

    def s(text):
        clean, h = g.scrub_claims(text)
        hits.extend(h)
        return clean

    sections["executive_summary"] = s(sections.get("executive_summary", ""))
    sections["measurement_analysis"] = s(sections.get("measurement_analysis", ""))
    for d in sections["defect_descriptions"]:
        d["description"] = s(d.get("description", ""))
    for r in sections["root_causes"]:
        r["hypothesis"], r["evidence"] = s(r["hypothesis"]), s(r.get("evidence", ""))
    for a in sections["recommended_actions"]:
        a["action"] = s(a["action"])
    sections["containment_actions"] = [s(x) for x in sections["containment_actions"]]
    return hits


def apply_output_guardrails(sections: dict, f: dict, c: dict) -> list[dict]:
    checks = []
    valid = {x["code"] for x in c["codes"]}
    defaults = {x["code"]: x["default_severity"] for x in c["codes"]}
    checks.append(g.enforce_codes(sections["defect_descriptions"], valid))
    checks.append(g.enforce_severity(sections["defect_descriptions"], defaults))

    known = {d["part_serial"] for d in c["defects"]} | {o["part_serial"] for o in c["out_of_spec"]}
    bad_refs = []
    for d in sections["defect_descriptions"]:
        good = [e for e in d.get("evidence", []) if e in known]
        bad_refs += [e for e in d.get("evidence", []) if e not in known]
        d["evidence"] = good
    checks.append(g.check("Evidence references real parts", g.WARN if bad_refs else g.PASS,
                          f"{len(bad_refs)} unknown part reference(s) removed." if bad_refs
                          else "Every cited part serial exists in the inspection data.", bad_refs))

    hits = _scrub(sections)
    checks.append(g.check("No unsupported claims", g.WARN if hits else g.PASS,
                          f"{len(hits)} absolute claim(s) removed (needs human sign-off)." if hits
                          else "No compliance or 'zero defect' claims made by the AI.", hits))
    checks.append(g.verify_numbers(_all_text(sections), f))
    checks.append(g.flag_low_confidence(c["defects"], LOW_CONF))
    return checks


# ---------------------------------------------------------------- main entry point
def _images(c: dict, limit: int = 3) -> list[dict]:
    from app.services.inspection_source import get_store
    out = []
    for d in c["defects"]:
        if d["image_id"] and len(out) < limit:
            p = get_store().image_path(d["image_id"])
            if p:
                out.append({"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}})
    return out


def generate(store: SyntheticSource, lot: str, user: dict) -> dict:
    t0 = time.perf_counter()
    c = collect(store, lot)
    f = llm_facts(c)
    findings, in_stats = build_notes(store, c["checks"], c["codes"])
    guard = [
        g.check("Prompt-injection filter", g.WARN if in_stats["injections_removed"] else g.PASS,
                f"{len(in_stats['injections_removed'])} instruction-like text(s) removed from inspector notes."
                if in_stats["injections_removed"] else "No instruction-like text found in inspector notes.",
                [x.strip()[:120] for x in in_stats["injections_removed"]]),
        g.check("Personal data masked", g.PASS,
                f"{len(in_stats['pii_masked'])} item(s) masked before sending to the AI." if in_stats["pii_masked"]
                else "No personal data found in the inputs.", sorted(set(in_stats["pii_masked"]))),
    ]
    notes_text = "\n".join(f"- [{x['item']} / {x['result']}] {x['note']}" for x in findings) or "(no notes)"
    codes_text = ", ".join(f"{x['code']}={x['name']}" for x in c["codes"])
    facts_json = g.cap_text(json.dumps(f, default=str), 30_000)
    user_text = prompts.REPORT_USER.format(lot=lot, codes=codes_text, facts=facts_json,
                                           notes=g.wrap_untrusted("inspector_notes", notes_text))

    mode, meta, sections = "template", {"provider": config.LLM_PROVIDER, "model": "template", "latency_ms": 0}, None
    if not ai.is_mock():
        content = user_text
        if config.LLM_VISION and config.LLM_PROVIDER in ("openai", "azure"):
            imgs = _images(c)
            if imgs:
                content = [{"type": "text", "text": user_text}] + imgs
        raw, meta = ai.call("report.generate", user, [{"role": "user", "content": content}], prompts.REPORT_SYSTEM,
                            as_json=True, temperature=config.REPORT_TEMPERATURE,
                            guard_meta={"input": {k: len(v) for k, v in in_stats.items()}})
        if raw is not None:
            try:
                sections = LLMReport.model_validate(raw).model_dump()
                mode = "llm"
            except ValidationError as e:
                guard.append(g.check("AI output format", g.WARN, "AI output did not match the report template; "
                                                                 "template sections used instead.", [str(e)[:300]]))
                mode = "fallback"
        else:
            guard.append(g.check("AI availability", g.WARN, "AI call failed - report written from computed facts "
                                                            "by the template (no AI text).", [meta.get("error", "")[:300]]))
            mode = "fallback"
    if sections is None:
        sections = template_sections(f, findings)
    else:
        guard.append(g.check("AI output format", g.PASS, "AI output matched the report template schema."))

    guard += apply_output_guardrails(sections, f, c)
    lr = c["lot_row"]
    elapsed = round(time.perf_counter() - t0, 2)
    now = datetime.now().replace(microsecond=0)
    report = {
        "meta": {"lot": lot, "line": lr.line, "line_name": c["line"]["name"], "part": c["line"]["part"],
                 "shift": lr["shift"], "shift_start": lr.shift_start.isoformat(), "shift_end": lr.shift_end.isoformat(),
                 "lot_size": int(lr.lot_size), "sampled": int(lr.sampled), "created_at": now.isoformat(),
                 "created_by": user["username"], "gauges": c["gauges"], "template": "QIR-STD-01 (synthetic)"},
        "kpis": c["kpis"], "features": c["features"], "pareto": c["pareto"], "defects": c["defects"],
        "out_of_spec": c["out_of_spec"], "manual_findings": findings, "insights": c["insights"],
        "maintenance": c["maintenance"], "material": c["material"], "sections": sections, "guardrails": guard,
        "signoffs": {"submitted_by": "", "submitted_at": "", "reviewed_by": "", "reviewed_at": "",
                     "approved_by": "", "approved_at": "", "escalated_at": "", "escalated_by": "", "comments": []},
        "ai": {"mode": mode, "provider": meta.get("provider"), "model": meta.get("model"),
               "prompt_version": config.PROMPT_VERSION, "latency_ms": meta.get("latency_ms", 0),
               "generation_seconds": elapsed, "manual_baseline_minutes": MANUAL_BASELINE_MIN,
               "label": "AI-generated draft - pending human review"},
    }
    sections["purpose"] = purpose_text(report["meta"], report["features"], report["material"])
    return report


def rewrite_section(report: dict, section: str, instruction: str, user: dict) -> dict:
    """AI rewrite of one text section. Returns a proposal; nothing is saved until the user accepts it."""
    allowed = {"executive_summary", "measurement_analysis"}
    if section not in allowed:
        raise ValueError(f"Only these sections can be rewritten by AI: {', '.join(sorted(allowed))}")
    current = report["sections"].get(section, "")
    ok, reason = g.check_question(instruction or "rewrite report summary", max_len=500)
    if not ok and g.looks_like_injection(instruction):
        raise ValueError(reason)
    facts = {"kpis": report["kpis"], "features": report["features"], "pareto": report["pareto"],
             "out_of_spec_count": len(report["out_of_spec"]), "lot_size": report["meta"]["lot_size"],
             "sampled": report["meta"]["sampled"],
             "insights": [{"title": i["title"], "metrics": i["metrics"]} for i in report.get("insights", [])]}
    if ai.is_mock():
        text = current.replace("  ", " ").strip()
        sentences = [s.strip() for s in text.split(". ") if s.strip()]
        text = ". ".join(sentences[:4]).rstrip(".") + "." if sentences else current
        mode = "template"
    else:
        msg = (f"FACTS: {json.dumps(facts, default=str)}\n\nCURRENT SECTION ({section}):\n"
               f"{g.wrap_untrusted('current_section', current)}\n\nINSTRUCTION: {instruction or 'Make it clearer and more concise.'}")
        raw, meta = ai.call("report.rewrite", user, [{"role": "user", "content": msg}], prompts.REWRITE_SYSTEM,
                            as_json=True, schema_hint='{"text": str}', temperature=config.REPORT_TEMPERATURE)
        if raw is None or not isinstance(raw, dict) or not raw.get("text"):
            raise RuntimeError("AI rewrite failed: " + (meta.get("error") or "no text returned"))
        text, mode = str(raw["text"]), "llm"
    text, hits = g.scrub_claims(text)
    num_check = g.verify_numbers(text, {**facts, "current": current})
    return {"section": section, "proposal": text, "mode": mode,
            "guardrails": [num_check, g.check("No unsupported claims", g.WARN if hits else g.PASS,
                                              f"{len(hits)} claim(s) removed." if hits else "No absolute claims.", hits)]}
