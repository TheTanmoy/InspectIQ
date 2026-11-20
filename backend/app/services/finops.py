"""FinOps: AI token cost, run cost (support & maintenance) and the cost-benefit case.

All prices and business assumptions live in one editable settings object (stored in the db `meta` table).
Defaults are ASSUMPTIONS for a synthetic plant - replace them with your contract rates and plant figures.
Every number shown in the FinOps and Cost-Benefit pages is computed here, never by the LLM.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta

from app.core import config, db

DEFAULT_SETTINGS = {
    "currency": "USD",  # every amount below is in US dollars (rupee figures converted at INR 84 = USD 1)
    # USD per 1 million tokens. Thinking tokens are billed as output.
    "pricing": {
        "gemini-3.8-flash": {"input_per_m": 0.50, "output_per_m": 3.00},
        "gemini-3.5-flash-lite": {"input_per_m": 0.10, "output_per_m": 0.40},
        "default": {"input_per_m": 0.50, "output_per_m": 3.00},
    },
    "pricing_note": "Assumed USD list prices per 1M tokens - replace with the rates in your Google Cloud contract.",
    # expected usage for the projection (whole plant, per working day)
    "volumes": {"reports_per_day": 9, "assistant_chats_per_day": 30, "insight_explains_per_day": 4,
                "rewrites_per_day": 6, "working_days_per_month": 26},
    # used when there is no measured usage yet for a purpose (tokens per call)
    "default_tokens": {"report.generate": [7000, 1400], "assistant.chat": [6500, 450],
                       "insights.explain": [1200, 300], "report.rewrite": [1500, 250]},
    "monthly_ai_budget_usd": 40.0,
    # support & maintenance run cost, USD per month
    "run_costs": {"hosting_usd": 107, "monitoring_backup_usd": 30, "it_support_hours": 20,
                  "it_hourly_rate_usd": 14.30, "model_prompt_review_hours": 6},
    # cost-benefit assumptions (Plant Quality Head)
    "cba": {
        "manual_minutes_per_report": 120, "ai_review_minutes_per_report": 20, "quality_staff_rate_usd_hour": 7.75,
        "scrap_cost_per_part_usd": 21.40, "defective_parts_contained_earlier_per_month": 40,
        "customer_claims_avoided_per_year": 2, "cost_per_customer_claim_usd": 8930,
        "audit_prep_hours_saved_per_month": 24, "one_time_implementation_usd": 17860, "horizon_months": 36,
    },
}

PURPOSE_LABEL = {"report.generate": "Report generation", "assistant.chat": "Assistant chat",
                 "insights.explain": "Insight explanation", "report.rewrite": "Section rewrite"}
VOLUME_KEY = {"report.generate": "reports_per_day", "assistant.chat": "assistant_chats_per_day",
              "insights.explain": "insight_explains_per_day", "report.rewrite": "rewrites_per_day"}
EDIT_SECTIONS = {"finops": {"pricing", "volumes", "monthly_ai_budget_usd", "run_costs"}, "cba": {"cba"}}


# ---------------------------------------------------------------- settings
def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings() -> dict:
    stored = db.get_meta("finops_settings", "")
    return _merge(DEFAULT_SETTINGS, json.loads(stored) if stored else {})


def _check_numbers(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_numbers(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, bool) or not isinstance(obj, (int, float)) or obj < 0:
        raise ValueError(f"'{path}' must be a number >= 0")


def update_settings(section: str, changes: dict) -> dict:
    allowed = EDIT_SECTIONS.get(section)
    if not allowed:
        raise ValueError("section must be 'finops' or 'cba'")
    bad = set(changes) - allowed
    if bad:
        raise ValueError(f"These settings cannot be changed here: {', '.join(sorted(bad))}")
    _check_numbers(changes)
    stored = json.loads(db.get_meta("finops_settings", "") or "{}")
    db.set_meta("finops_settings", json.dumps(_merge(stored, changes)))
    return settings()


def price(model: str, s: dict | None = None) -> dict:
    p = (s or settings())["pricing"]
    return p.get(model) or p["default"]


def call_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pr = price(model)
    return round(input_tokens / 1e6 * pr["input_per_m"] + output_tokens / 1e6 * pr["output_per_m"], 6)


# ---------------------------------------------------------------- usage + projection (IT / FinOps)
def _calls(days: int) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    return [dict(r) for r in db.query("SELECT * FROM llm_calls WHERE ts >= ? ORDER BY ts", (since,))]


def usage(days: int = 30) -> dict:
    s = settings()
    rows = _calls(days)
    for r in rows:  # re-price with current settings so a price change applies to the whole view
        r["cost_usd"] = call_cost_usd(r["model"], r["input_tokens"] or 0, (r["output_tokens"] or 0) + (r["thinking_tokens"] or 0))
    ok = [r for r in rows if r["ok"]]
    measured = [r for r in ok if (r["input_tokens"] or 0) > 0]
    tot = lambda key, rs=rows: int(sum(r[key] or 0 for r in rs))
    cost = round(sum(r["cost_usd"] for r in rows), 4)

    by_purpose, by_model, daily = {}, {}, {}
    for r in rows:
        bp = by_purpose.setdefault(r["purpose"], {"purpose": r["purpose"], "label": PURPOSE_LABEL.get(r["purpose"], r["purpose"]),
                                                 "calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
                                                 "cost_usd": 0.0, "latency_ms": 0, "errors": 0})
        bm = by_model.setdefault(r["model"], {"model": r["model"], "calls": 0, "tokens": 0, "cost_usd": 0.0, "errors": 0})
        dd = daily.setdefault(r["ts"][:10], {"day": r["ts"][:10], "calls": 0, "cost_usd": 0.0, "tokens": 0})
        tokens = (r["input_tokens"] or 0) + (r["output_tokens"] or 0) + (r["thinking_tokens"] or 0)
        for b in (bp,):
            b["calls"] += 1
            b["input_tokens"] += r["input_tokens"] or 0
            b["output_tokens"] += r["output_tokens"] or 0
            b["thinking_tokens"] += r["thinking_tokens"] or 0
            b["cost_usd"] += r["cost_usd"]
            b["latency_ms"] += r["latency_ms"] or 0
            b["errors"] += 0 if r["ok"] else 1
        bm["calls"] += 1
        bm["tokens"] += tokens
        bm["cost_usd"] += r["cost_usd"]
        bm["errors"] += 0 if r["ok"] else 1
        dd["calls"] += 1
        dd["cost_usd"] += r["cost_usd"]
        dd["tokens"] += tokens
    for b in by_purpose.values():
        b["avg_latency_ms"] = int(b.pop("latency_ms") / max(b["calls"], 1))
        b["cost_usd"] = round(b["cost_usd"], 5)
    for b in by_model.values():
        b["cost_usd"] = round(b["cost_usd"], 5)
    for d in daily.values():
        d["cost_usd"] = round(d["cost_usd"], 5)

    proj = projection(s, measured)
    fallback_calls = sum(1 for r in ok if config.LLM_FALLBACK_MODEL and r["model"] == config.LLM_FALLBACK_MODEL)
    return {
        "window_days": days, "settings": s,
        "models": {"primary": config.LLM_MODEL, "fallback": config.LLM_FALLBACK_MODEL, "provider": config.LLM_PROVIDER},
        "kpis": {"calls": len(rows), "errors": len(rows) - len(ok),
                 "error_rate_pct": round(100 * (len(rows) - len(ok)) / len(rows), 1) if rows else 0.0,
                 "fallback_rate_pct": round(100 * fallback_calls / len(ok), 1) if ok else 0.0,
                 "input_tokens": tot("input_tokens"), "output_tokens": tot("output_tokens"),
                 "thinking_tokens": tot("thinking_tokens"), "cost_usd": cost,
                 "avg_latency_ms": int(sum(r["latency_ms"] or 0 for r in ok) / len(ok)) if ok else 0,
                 "measured_calls": len(measured), "estimated_calls": sum(1 for r in rows if r["estimated"])},
        "by_purpose": sorted(by_purpose.values(), key=lambda b: -b["cost_usd"]),
        "by_model": sorted(by_model.values(), key=lambda b: -b["cost_usd"]),
        "daily": sorted(daily.values(), key=lambda d: d["day"]),
        "recent": [{k: r[k] for k in ("ts", "username", "purpose", "model", "latency_ms", "ok", "input_tokens",
                                      "output_tokens", "thinking_tokens", "estimated", "cost_usd", "error")}
                   for r in reversed(rows[-25:])],
        "projection": proj,
        "support_maintenance": run_cost(s, proj["monthly_usd"]),
    }


def projection(s: dict, measured: list[dict]) -> dict:
    """Monthly token cost forecast = expected calls x tokens per call (measured average, else default) x price."""
    v = s["volumes"]
    primary = price(config.LLM_MODEL, s)
    lines, total = [], 0.0
    for purpose, vol_key in VOLUME_KEY.items():
        ms = [r for r in measured if r["purpose"] == purpose]
        if ms:
            tin = sum(r["input_tokens"] for r in ms) / len(ms)
            tout = sum((r["output_tokens"] or 0) + (r["thinking_tokens"] or 0) for r in ms) / len(ms)
            basis = f"measured ({len(ms)} calls)"
        else:
            tin, tout = s["default_tokens"][purpose]
            basis = "assumed default"
        calls_month = v[vol_key] * v["working_days_per_month"]
        cost_call = tin / 1e6 * primary["input_per_m"] + tout / 1e6 * primary["output_per_m"]
        month = calls_month * cost_call
        total += month
        lines.append({"purpose": purpose, "label": PURPOSE_LABEL[purpose], "calls_per_month": calls_month,
                      "avg_input_tokens": int(tin), "avg_output_tokens": int(tout), "basis": basis,
                      "cost_per_call_usd": round(cost_call, 5), "monthly_usd": round(month, 2)})
    budget = s["monthly_ai_budget_usd"]
    return {"priced_at": config.LLM_MODEL, "lines": lines, "monthly_usd": round(total, 2),
            "annual_usd": round(total * 12, 2), "budget_usd": budget,
            "budget_used_pct": round(100 * total / budget, 1) if budget else None,
            "cost_per_report_usd": next((ln["cost_per_call_usd"] for ln in lines if ln["purpose"] == "report.generate"), 0)}


def run_cost(s: dict, token_monthly_usd: float) -> dict:
    rc = s["run_costs"]
    items = [
        {"item": "AI tokens (projected)", "owner": "IT / FinOps", "monthly_usd": round(token_monthly_usd, 2)},
        {"item": "Hosting (app server + database)", "owner": "IT Infrastructure", "monthly_usd": round(rc["hosting_usd"], 2)},
        {"item": "Monitoring, backup & security patching tools", "owner": "IT Operations",
         "monthly_usd": round(rc["monitoring_backup_usd"], 2)},
        {"item": f"Application support ({rc['it_support_hours']:g} h)", "owner": "IT Support",
         "monthly_usd": round(rc["it_support_hours"] * rc["it_hourly_rate_usd"], 2)},
        {"item": f"Prompt, model & rulebook review ({rc['model_prompt_review_hours']:g} h)", "owner": "IT + Quality",
         "monthly_usd": round(rc["model_prompt_review_hours"] * rc["it_hourly_rate_usd"], 2)},
    ]
    total = round(sum(i["monthly_usd"] for i in items), 2)
    return {"items": items, "monthly_usd": total, "annual_usd": round(total * 12, 2)}


# ---------------------------------------------------------------- cost-benefit (Plant Quality Head)
def cost_benefit() -> dict:
    s = settings()
    u = usage(30)
    c, v = s["cba"], s["volumes"]
    reports_month = v["reports_per_day"] * v["working_days_per_month"]
    rate = c["quality_staff_rate_usd_hour"]
    hours_saved = reports_month * max(c["manual_minutes_per_report"] - c["ai_review_minutes_per_report"], 0) / 60
    benefits = [
        {"item": "Report preparation time saved", "monthly_usd": round(hours_saved * rate, 2),
         "basis": f"{reports_month} reports x ({c['manual_minutes_per_report']} - {c['ai_review_minutes_per_report']}) min "
                  f"= {hours_saved:.0f} h x ${rate:,.2f}/h"},
        {"item": "Audit preparation time saved", "monthly_usd": round(c["audit_prep_hours_saved_per_month"] * rate, 2),
         "basis": f"{c['audit_prep_hours_saved_per_month']} h/month x ${rate:,.2f}/h (versioned, audited records)"},
        {"item": "Scrap avoided by earlier containment", "monthly_usd": round(
            c["defective_parts_contained_earlier_per_month"] * c["scrap_cost_per_part_usd"], 2),
         "basis": f"{c['defective_parts_contained_earlier_per_month']} parts/month x ${c['scrap_cost_per_part_usd']:,.2f} "
                  "(patterns such as the bad L3 heat found days earlier)"},
        {"item": "Customer claims avoided", "monthly_usd": round(
            c["customer_claims_avoided_per_year"] * c["cost_per_customer_claim_usd"] / 12, 2),
         "basis": f"{c['customer_claims_avoided_per_year']:g} claims/year x ${c['cost_per_customer_claim_usd']:,.0f} / 12"},
    ]
    sm = u["support_maintenance"]
    benefit_m = round(sum(b["monthly_usd"] for b in benefits), 2)
    cost_m = sm["monthly_usd"]
    net_m = round(benefit_m - cost_m, 2)
    one_time = c["one_time_implementation_usd"]
    horizon = int(c["horizon_months"])
    cumulative, cum = [], -one_time
    payback = None
    for m in range(0, horizon + 1):
        if m:
            cum += net_m
        cumulative.append({"month": m, "cumulative_usd": round(cum, 2)})
        if payback is None and cum >= 0:
            payback = m
    total_cost = one_time + cost_m * horizon
    total_benefit = benefit_m * horizon
    return {
        "settings": c, "volumes": v, "reports_per_month": reports_month, "hours_saved_per_month": round(hours_saved, 1),
        "fte_equivalent": round(hours_saved / 160, 2),
        "currency": "USD", "benefits": benefits, "costs": sm["items"], "benefit_monthly_usd": benefit_m,
        "cost_monthly_usd": cost_m, "net_monthly_usd": net_m, "one_time_usd": one_time, "horizon_months": horizon,
        "roi_pct": round(100 * (total_benefit - total_cost) / total_cost, 1) if total_cost else None,
        "payback_months": payback, "net_over_horizon_usd": round(total_benefit - total_cost, 2),
        "benefit_cost_ratio": round(total_benefit / total_cost, 2) if total_cost else None,
        "token_share_of_run_cost_pct": round(100 * sm["items"][0]["monthly_usd"] / cost_m, 1) if cost_m else 0,
        "cumulative": cumulative,
        "note": "All figures are assumptions for a synthetic plant. Edit them to match your plant before deciding.",
    }
