"""Analytics, report generation, compliance engine and workflow (no web server needed)."""
import pytest

from app.services import analytics, compliance, report_builder, reports


def test_planted_patterns_detected(ready):
    types = {i["type"] for i in analytics.detect_patterns(ready)}
    assert {"shift_spike", "drift", "calibration", "material"} <= types


def test_material_pattern_is_the_l3_bad_heat_not_l1_process(ready, users):
    ins = analytics.detect_patterns(ready)
    mat = [i for i in ins if i["type"] == "material"]
    assert [(i["line"], i["defect_code"]) for i in mat] == [("L3", "D-PIT")]
    assert ready.material(mat[0]["material_lot"])["deviation_ref"]
    # pitting rises on every L3 shift, so it must not be reported as a shift-specific spike
    assert not any(i["type"] == "shift_spike" and i["line"] == "L3" for i in ins)
    lots = ready.lots()
    lot = lots[lots.material_lot == mat[0]["material_lot"]].lot.iloc[-1]
    rep = report_builder.generate(ready, lot, users["inspector"])
    assert rep["material"]["deviations"]
    assert any(i["type"] == "material" for i in rep["insights"])
    r13 = next(r for r in compliance.evaluate(rep)["results"] if r["rule_id"] == "R-013")
    assert r13["result"] == "warn"


def test_report_generation_and_guardrails(ready, users):
    lots = ready.lots()
    lot = lots[(lots.line == "L1") & (lots["shift"] == "C")].lot.iloc[-1]  # contains the planted injection
    rep = report_builder.generate(ready, lot, users["inspector"])
    checks = {c["check"]: c for c in rep["guardrails"]}
    assert checks["Prompt-injection filter"]["status"] == "warn"
    assert rep["sections"]["executive_summary"]
    assert rep["ai"]["mode"] == "template"
    assert rep["kpis"]["parts_inspected"] > 0


def test_workflow_and_compliance(ready, users):
    lots = ready.lots()
    lot = lots[lots.line == "L3"].lot.iloc[-1]
    rep = reports.save_new(report_builder.generate(ready, lot, users["inspector"]), users["inspector"])
    rid = rep["id"]
    with pytest.raises(reports.WorkflowError):
        reports.transition(rid, "approve", users["qm"])  # not reviewed yet
    reports.transition(rid, "submit", users["inspector"])
    reports.transition(rid, "review", users["supervisor"])
    current = reports.get(rid)
    if not current["compliance"]["can_approve"]:
        with pytest.raises(reports.WorkflowError):
            reports.transition(rid, "approve", users["qm"])


def test_rule_edit_versions_and_validation(ready, users):
    v0 = compliance.rulebook_version()
    rule = compliance.update_rule("R-001", {"params": {"hours": 12}}, users["compliance"], "test")
    assert rule["params"]["hours"] == 12 and compliance.rulebook_version() == v0 + 1
    assert len(compliance.history("R-001")) >= 2
    with pytest.raises(ValueError):
        compliance.update_rule("R-001", {"params": {"hours": -1}}, users["compliance"])
    with pytest.raises(ValueError):
        compliance.update_rule("R-001", {"type": "deadline"}, users["compliance"])
    compliance.update_rule("R-001", {"params": {"hours": 24}}, users["compliance"], "restore")


def test_purpose_section_and_segregation_of_duties(ready, users):
    lots = ready.lots()
    lot = lots[lots.line == "L1"].lot.iloc[-2]
    rep = reports.save_new(report_builder.generate(ready, lot, users["qm"]), users["qm"])
    rid = rep["id"]
    assert rep["sections"]["purpose"].startswith("Purpose:") and lot in rep["sections"]["purpose"]
    chain = reports.get(rid)["approval_chain"]
    assert [c["key"] for c in chain if c["key"] != "escalate"] == ["prepare", "review", "approve"]
    reports.transition(rid, "submit", users["qm"])
    with pytest.raises(reports.WorkflowError, match="Segregation"):
        reports.transition(rid, "review", users["qm"])  # cannot review own submission
    reports.transition(rid, "review", users["supervisor"])
    with pytest.raises(reports.WorkflowError, match="Segregation"):
        reports.transition(rid, "approve", users["qm"])  # submitter cannot approve
    assert reports.get(rid)["approval_chain"][-1]["state"] == "current"


def test_high_risk_report_needs_plant_quality_head_release(ready, users):
    lots = ready.lots()
    bad = next(i for i in analytics.detect_patterns(ready) if i["type"] == "material")["material_lot"]
    lot = lots[(lots.material_lot == bad) & (lots.line == "L3")].sort_values("shift_end").lot.iloc[-1]
    rep = reports.save_new(report_builder.generate(ready, lot, users["inspector"]), users["inspector"])
    rid = rep["id"]
    assert reports.risk_reasons(rep)
    # clear the ordinary blockers an inspector would handle: dispositions + low-confidence verification
    reports.update(rid, {"dispositions": {i: "hold" for i in range(len(rep["out_of_spec"]))},
                         "verify": [d["id"] for d in rep["defects"]]}, users["inspector"])
    reports.transition(rid, "submit", users["inspector"])
    reports.transition(rid, "review", users["supervisor"])
    current = reports.get(rid)
    assert current["compliance"]["can_approve"], current["compliance"]["blocking_failures"]
    reports.transition(rid, "approve", users["qm"])
    current = reports.get(rid)
    assert current["status"] == "awaiting_release"
    assert current["approval_chain"][-1]["key"] == "release" and current["approval_chain"][-1]["state"] == "current"
    with pytest.raises(reports.WorkflowError):
        reports.update(rid, {"sections": {"purpose": "x"}}, users["qm"])  # locked while awaiting release
    reports.transition(rid, "release", users["head"])
    assert reports.get(rid)["status"] == "approved"


def test_finops_token_cost_and_cost_benefit(ready, users):
    from app.core import audit
    from app.services import finops
    audit.log_llm_call("qm", "report.generate", "gemini", "gemini-3.8-flash", "v1", 900, True,
                       usage={"input_tokens": 8000, "output_tokens": 1000, "thinking_tokens": 500, "requests": 1})
    u = finops.usage(30)
    assert u["kpis"]["input_tokens"] >= 8000 and u["kpis"]["cost_usd"] > 0
    # 8000 in x 0.50 + 1500 out x 3.00 per 1M tokens
    assert abs(finops.call_cost_usd("gemini-3.8-flash", 8000, 1500) - 0.0085) < 1e-9
    assert u["projection"]["monthly_usd"] > 0 and u["support_maintenance"]["monthly_inr"] > 0
    cba = finops.cost_benefit()
    assert cba["benefit_monthly_inr"] > cba["cost_monthly_inr"] and cba["payback_months"] is not None
    finops.update_settings("cba", {"cba": {"horizon_months": 24}})
    assert finops.cost_benefit()["horizon_months"] == 24
    with pytest.raises(ValueError):
        finops.update_settings("cba", {"pricing": {}})  # pricing is IT's section
    with pytest.raises(ValueError):
        finops.update_settings("finops", {"usd_to_inr": -1})
