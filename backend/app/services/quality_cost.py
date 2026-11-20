"""Cost of poor quality (COPQ) for the Plant Quality Head: history + projected savings if issues are resolved.

History  - every lot's sampled defect rate is extrapolated to the full lot size and costed as scrap or rework
           by severity, giving a weekly scrap / rework cost per line over the whole data history.
Issues   - each detected pattern (shift spike, raw-material heat, drift, expired gauge) is costed as the EXCESS
           defects above that line's normal rate, from the day the issue started until now.
Forecast - monthly saving if the issue is resolved now, minus a one-time fix cost -> payback and 12-month net.

Every amount is USD and every number is computed here from the inspection data plus editable assumptions.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta

import pandas as pd

from app.core import db
from app.services import analytics
from app.services.inspection_source import SyntheticSource

DEFAULTS = {
    "currency": "USD",
    # value of one finished part (material + machining) - what is lost when it is scrapped
    "part_cost_usd": {"L1": 38.0, "L2": 52.0, "L3": 29.0},
    # cost to rework one part instead of scrapping it
    "rework_cost_usd": {"L1": 6.0, "L2": 8.0, "L3": 5.0},
    # share of defective parts that end up scrapped (the rest is reworked)
    "scrap_share": {"critical": 1.0, "major": 0.5, "minor": 0.1},
    # one-time cost to resolve each kind of issue
    "fix_cost_usd": {"shift_spike": 1500, "material": 2500, "drift": 900, "calibration": 250},
    # re-measuring parts that were checked with an expired gauge
    "reverify_cost_per_part_usd": 0.6,
    "projection_months": 12,
}
LABEL = {"shift_spike": "Process (shift-specific)", "material": "Raw material", "drift": "Tool wear / drift",
         "calibration": "Measurement system"}
FIX = {"shift_spike": "Inspect / replace the changed tooling and re-validate the shift's process parameters",
       "material": "Quarantine the heat, sort affected stock, raise a supplier corrective action",
       "drift": "Change or dress the wheel / tool and re-centre the process",
       "calibration": "Calibrate the gauge and re-verify parts measured since it expired"}


# ---------------------------------------------------------------- settings
def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings() -> dict:
    raw = db.get_meta("quality_cost_settings", "")
    return _merge(DEFAULTS, json.loads(raw) if raw else {})


def _check(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, bool) or not isinstance(obj, (int, float)) or obj < 0:
        raise ValueError(f"'{path}' must be a number >= 0")


def update_settings(changes: dict) -> dict:
    bad = set(changes) - (set(DEFAULTS) - {"currency"})
    if bad:
        raise ValueError(f"Unknown setting(s): {', '.join(sorted(bad))}")
    _check(changes)
    if any(v > 1 for v in changes.get("scrap_share", {}).values()):
        raise ValueError("scrap_share values must be between 0 and 1")
    stored = json.loads(db.get_meta("quality_cost_settings", "") or "{}")
    db.set_meta("quality_cost_settings", json.dumps(_merge(stored, changes)))
    return settings()


# ---------------------------------------------------------------- building blocks
def _unit_costs(s: dict, line: str, severity: str) -> tuple[float, float]:
    """(scrap $, rework $) for one defective part of this line and severity."""
    share = s["scrap_share"].get(severity, 0.5)
    return share * s["part_cost_usd"].get(line, 40.0), (1 - share) * s["rework_cost_usd"].get(line, 6.0)


def _lot_frame(store: SyntheticSource, s: dict) -> pd.DataFrame:
    """One row per lot: produced, sampled, estimated defective parts and scrap / rework cost for the whole lot."""
    lots = store.lots().copy()
    meas, det = store.measurements(), store.detections()
    sev_rank = {"minor": 0, "major": 1, "critical": 2}
    part_sev = (det.assign(r=det.severity.map(sev_rank)).sort_values("r")
                .drop_duplicates("part_serial", keep="last")[["part_serial", "lot", "severity"]])
    oos = meas.loc[~meas.in_spec.astype(bool), ["part_serial", "lot"]].drop_duplicates("part_serial")
    oos = oos[~oos.part_serial.isin(part_sev.part_serial)].assign(severity="major")  # dimensional = major
    bad = pd.concat([part_sev, oos], ignore_index=True)
    bad["line"] = bad.lot.str.split("-").str[1]
    costs = bad.apply(lambda r: _unit_costs(s, r.line, r.severity), axis=1, result_type="expand")
    bad["scrap"], bad["rework"] = costs[0], costs[1]
    agg = bad.groupby("lot").agg(defective=("part_serial", "count"), scrap=("scrap", "sum"), rework=("rework", "sum"))
    inspected = meas.groupby("lot").part_serial.nunique().rename("inspected")
    lots = lots.merge(agg, left_on="lot", right_index=True, how="left").merge(
        inspected, left_on="lot", right_index=True, how="left").fillna({"defective": 0, "scrap": 0, "rework": 0})
    lots["inspected"] = lots["inspected"].fillna(lots["sampled"]).clip(lower=1)
    k = lots.lot_size / lots.inspected  # extrapolate the sample to the lot
    lots["est_defective"] = lots.defective * k
    lots["scrap_usd"], lots["rework_usd"] = lots.scrap * k, lots.rework * k
    lots["copq_usd"] = lots.scrap_usd + lots.rework_usd
    lots["day"] = pd.to_datetime(lots["date"])
    return lots


def _code_rate(store: SyntheticSource, lots: pd.DataFrame, code: str) -> pd.Series:
    """Detections of one defect code per inspected part, per lot."""
    det = store.detections()
    n = det[det.defect_code == code].groupby("lot").size()
    return (lots.lot.map(n).fillna(0) / lots.inspected).rename("rate")


def _p_out(mean: float, sd: float, lsl: float, usl: float) -> float:
    if sd <= 0:
        return 0.0
    cdf = lambda x: 0.5 * (1 + math.erf((x - mean) / (sd * math.sqrt(2))))
    return (1 - cdf(usl)) + (cdf(lsl) if lsl > 0 else 0.0)


def _months(days: float) -> float:
    return max(days, 1) / 30.4


# ---------------------------------------------------------------- per-issue costing
def _issue(store, lots, s, ins, end) -> dict | None:
    line, typ = ins["line"], ins["type"]
    ll = lots[lots.line == line]
    if ll.empty:
        return None
    daily_line_output = ll.groupby("day").lot_size.sum().mean()
    out = {"id": ins["id"], "type": typ, "category": LABEL.get(typ, typ), "line": line, "title": ins["title"],
           "fix": FIX.get(typ, ""), "fix_cost_usd": float(s["fix_cost_usd"].get(typ, 1000))}

    if typ in ("shift_spike", "material"):
        code = ins["defect_code"]
        sev = next((c["default_severity"] for c in store.defect_codes() if c["code"] == code), "major")
        scrap1, rework1 = _unit_costs(s, line, sev)
        rate = _code_rate(store, ll, code)
        if typ == "shift_spike":
            scope_mask = ll["shift"] == ins["shift"]
            maint = store.maintenance()
            ev = maint[(maint.line == line) & (maint.ts >= end - timedelta(days=18)) & (maint.ts <= end)]
            onset = (ev.ts.max() if not ev.empty else end - timedelta(days=14)).normalize()
            in_scope = scope_mask & (ll.day >= onset)
            base_mask = scope_mask & (ll.day < onset)
        else:
            m = store.material(ins["material_lot"]) or {}
            onset = pd.Timestamp(m.get("first_used") or (end - timedelta(days=14)))
            in_scope = ll.material_lot == ins["material_lot"]
            base_mask = ~in_scope
        trend_mask = scope_mask if typ == "shift_spike" else pd.Series(True, index=ll.index)
        tl = ll[trend_mask].assign(r=rate[trend_mask], w=ll.loc[trend_mask, "day"].dt.to_period("W-SUN").dt.start_time,
                                   hit=rate[trend_mask] * ll.loc[trend_mask, "inspected"])
        produced = float(ll.loc[in_scope, "lot_size"].sum())
        scope_rate = float((rate[in_scope] * ll.loc[in_scope, "inspected"]).sum() / max(ll.loc[in_scope, "inspected"].sum(), 1))
        base_rate = float((rate[base_mask] * ll.loc[base_mask, "inspected"]).sum() / max(ll.loc[base_mask, "inspected"].sum(), 1))
        excess = max(scope_rate - base_rate, 0.0)
        days = max((end.normalize() - onset).days + 1, 1)
        excess_parts = excess * produced
        monthly_parts = excess * produced / _months(days)
        trend = []
        for w, gw in tl.groupby("w"):
            r_w = float(gw.hit.sum() / max(gw.inspected.sum(), 1))
            exc_w = float(sum(max(rr - base_rate, 0) * sz for rr, sz in zip(gw.r, gw.lot_size)
                              if (typ == "material" and in_scope.loc[gw.index].any()) or typ == "shift_spike"))
            if typ == "material":
                exc_w = float(sum(max(rr - base_rate, 0) * sz for rr, sz, ins_ in
                                  zip(gw.r, gw.lot_size, in_scope.loc[gw.index]) if ins_))
            elif typ == "shift_spike":
                exc_w = float(sum(max(rr - base_rate, 0) * sz for rr, sz, d in zip(gw.r, gw.lot_size, gw.day) if d >= onset))
            trend.append({"week": str(w.date()), "rate_pct": round(100 * r_w, 2), "excess_cost_usd": round(exc_w * (scrap1 + rework1), 2)})
        out["trend"] = trend
        out.update(onset=str(onset.date()), days_active=days, produced_in_scope=round(produced),
                   rate_now_pct=round(100 * scope_rate, 2), rate_baseline_pct=round(100 * base_rate, 2),
                   excess_defective_to_date=round(excess_parts), scrap_to_date_usd=round(excess_parts * scrap1, 2),
                   rework_to_date_usd=round(excess_parts * rework1, 2),
                   monthly_loss_usd=round(monthly_parts * (scrap1 + rework1), 2),
                   basis=f"{100 * scope_rate:.2f}% vs normal {100 * base_rate:.2f}% {code} on {round(produced):,} parts produced")

    elif typ == "drift":
        meas = store.measurements()
        g = meas[(meas.line == line) & (meas.feature == ins["feature"])]
        lsl, usl = float(g.lsl.iloc[0]), float(g.usl.iloc[0])
        maint = store.maintenance()
        ev = maint[(maint.line == line) & (maint.station == ins.get("station"))]
        onset = (ev.ts.max() if not ev.empty else end - timedelta(days=20)).normalize()
        before = g[g.ts < onset]
        sd = float(before.value.std(ddof=1)) if len(before) > 10 else float(g.value.std(ddof=1))
        p_base = _p_out(float(before.value.mean()) if len(before) else float(g.nominal.iloc[0]), sd, lsl, usl)
        slope, now_mean = float(ins["metrics"]["slope_per_day"] or 0), float(ins["metrics"]["current_mean"])
        p_next = _p_out(now_mean + slope * 15, sd, lsl, usl)  # mid next month if nothing is done
        scrap1, rework1 = _unit_costs(s, line, "major")
        recent_lots = ll[ll.day >= onset]
        produced = float(recent_lots.lot_size.sum())
        oos_parts = g[(g.ts >= onset) & ~g.in_spec.astype(bool)].part_serial.nunique()
        insp = g[g.ts >= onset].part_serial.nunique() or 1
        excess_parts = max(oos_parts / insp - p_base, 0) * produced
        last7 = g[g.ts >= end - timedelta(days=7)]
        rate7 = last7[~last7.in_spec.astype(bool)].part_serial.nunique() / max(last7.part_serial.nunique(), 1)
        monthly_parts = max(rate7 - p_base, 0) * daily_line_output * 30.4  # observed run-rate, not the forecast
        gw = g[g.ts >= onset - timedelta(days=14)].assign(w=lambda x: x.ts.dt.to_period("W-SUN").dt.start_time)
        out["trend"] = [{"week": str(w.date()), "rate_pct": round(float(100 * (~x.in_spec.astype(bool)).groupby(x.part_serial).any().mean()), 2),
                         "mean": round(float(x.value.mean()), 4)} for w, x in gw.groupby("w")]
        days = max((end.normalize() - onset).days + 1, 1)
        out.update(onset=str(onset.date()), days_active=days, produced_in_scope=round(produced),
                   rate_now_pct=round(100 * oos_parts / insp, 2), rate_baseline_pct=round(100 * p_base, 2),
                   excess_defective_to_date=round(excess_parts), scrap_to_date_usd=round(excess_parts * scrap1, 2),
                   rework_to_date_usd=round(excess_parts * rework1, 2),
                   monthly_loss_usd=round(monthly_parts * (scrap1 + rework1), 2),
                   projected_oos_next_month_pct=round(100 * p_next, 2),
                   risk=(f"If nothing is done, about {100 * p_next:.0f}% of {ins['feature']} would be out of spec "
                         f"by mid next month (limit reached in ~{ins['metrics'].get('days_to_limit')} days)."),
                   basis=(f"{ins['feature']} out of spec {100 * rate7:.2f}% in the last 7 days "
                          f"(normal {100 * p_base:.2f}%), costed at today's rate"))

    elif typ == "calibration":
        due = pd.Timestamp(ins["metrics"]["calibration_due"])
        if due > end:
            return None
        produced = float(ll[ll.day >= due].lot_size.sum())
        cost = produced * s["reverify_cost_per_part_usd"]
        days = max((end.normalize() - due).days, 1)
        out.update(onset=str(due.date()), days_active=days, produced_in_scope=round(produced),
                   rate_now_pct=None, rate_baseline_pct=None, excess_defective_to_date=0,
                   scrap_to_date_usd=0.0, rework_to_date_usd=round(cost, 2),
                   monthly_loss_usd=round(daily_line_output * 30.4 * s["reverify_cost_per_part_usd"], 2),
                   basis=f"{round(produced):,} parts measured with an expired gauge must be re-verified "
                         f"at ${s['reverify_cost_per_part_usd']:.2f} each")
    else:
        return None

    out["cost_to_date_usd"] = round(out["scrap_to_date_usd"] + out["rework_to_date_usd"], 2)
    months = s["projection_months"]
    out["monthly_saving_if_fixed_usd"] = out["monthly_loss_usd"]
    out["net_over_horizon_usd"] = round(out["monthly_loss_usd"] * months - out["fix_cost_usd"], 2)
    out["payback_days"] = (round(30.4 * out["fix_cost_usd"] / out["monthly_loss_usd"], 1)
                           if out["monthly_loss_usd"] > 0 else None)
    return out


# ---------------------------------------------------------------- report
def report(store: SyntheticSource) -> dict:
    s = settings()
    lots = _lot_frame(store, s)
    end = store.lots().shift_end.max()

    # history: weekly cost of poor quality per line
    lots["week"] = lots.day.dt.to_period("W-SUN").dt.start_time
    wk = lots.groupby(["week", "line"]).agg(produced=("lot_size", "sum"), est_defective=("est_defective", "sum"),
                                            scrap_usd=("scrap_usd", "sum"), rework_usd=("rework_usd", "sum")).reset_index()
    wk["copq_usd"] = wk.scrap_usd + wk.rework_usd
    history = [{"week": str(r.week.date()), "line": r.line, "produced": int(r.produced), "est_defective": round(r.est_defective),
                "scrap_usd": round(r.scrap_usd, 2), "rework_usd": round(r.rework_usd, 2), "copq_usd": round(r.copq_usd, 2),
                "per_1000_usd": round(1000 * r.copq_usd / r.produced, 2) if r.produced else 0} for r in wk.itertuples()]
    by_line = (lots.groupby("line").agg(produced=("lot_size", "sum"), scrap_usd=("scrap_usd", "sum"),
                                        rework_usd=("rework_usd", "sum"), est_defective=("est_defective", "sum")).reset_index())
    days_hist = max((lots.day.max() - lots.day.min()).days + 1, 1)
    lines = [{"line": r.line, "part": (store.line(r.line) or {}).get("part", r.line), "produced": int(r.produced),
              "est_defective": round(r.est_defective), "scrap_usd": round(r.scrap_usd, 2), "rework_usd": round(r.rework_usd, 2),
              "copq_usd": round(r.scrap_usd + r.rework_usd, 2),
              "monthly_copq_usd": round((r.scrap_usd + r.rework_usd) / _months(days_hist), 2)} for r in by_line.itertuples()]

    issues = [i for i in (_issue(store, lots, s, ins, end) for ins in analytics.detect_patterns(store)) if i]
    issues.sort(key=lambda i: -i["monthly_loss_usd"])

    # current run-rate = last 14 days (all issues active), per month; plus re-verification for expired gauges
    last_day = lots.day.max()
    recent = lots[lots.day > last_day - timedelta(days=14)]
    run_defects = float(recent.copq_usd.sum()) / _months(14)
    run_scrap = float(recent.scrap_usd.sum()) / _months(14)
    reverify = sum(i["monthly_loss_usd"] for i in issues if i["type"] == "calibration")
    run_rate = run_defects + reverify

    # history anchor: cost per part BEFORE the first issue started = the level the plant can return to
    first_onset = min((pd.Timestamp(i["onset"]) for i in issues), default=last_day)
    before = lots[lots.day < first_onset]
    per_part_before = float(before.copq_usd.sum() / before.lot_size.sum()) if before.lot_size.sum() else 0.0
    baseline = per_part_before * float(recent.lot_size.sum()) / _months(14)
    gross = sum(i["monthly_saving_if_fixed_usd"] for i in issues)
    after = max(run_rate - gross, min(baseline, run_rate))  # issues overlap: cannot go below the pre-issue level
    savings = run_rate - after
    scale = savings / gross if gross else 0.0
    for i in issues:  # share the achievable saving across issues in proportion to their own estimate
        i["monthly_saving_if_fixed_usd"] = round(i["monthly_loss_usd"] * scale, 2)
        i["net_over_horizon_usd"] = round(i["monthly_saving_if_fixed_usd"] * s["projection_months"] - i["fix_cost_usd"], 2)
        i["payback_days"] = (round(30.4 * i["fix_cost_usd"] / i["monthly_saving_if_fixed_usd"], 1)
                             if i["monthly_saving_if_fixed_usd"] > 0 else None)
    fix = sum(i["fix_cost_usd"] for i in issues)
    months = int(s["projection_months"])

    projection, cum = [], -fix
    payback = None
    for m in range(0, months + 1):
        if m:
            cum += savings
        projection.append({"month": m, "copq_if_unresolved_usd": round(run_rate, 2), "copq_if_resolved_usd": round(after, 2),
                           "cumulative_net_saving_usd": round(cum, 2)})
        if payback is None and cum >= 0:
            payback = m

    total_hist = float(lots.copq_usd.sum())
    return {
        "currency": "USD", "settings": s,
        "window": {"from": str(lots.day.min().date()), "to": str(lots.day.max().date()), "days": int(days_hist)},
        "kpis": {"copq_history_usd": round(total_hist, 2), "scrap_history_usd": round(float(lots.scrap_usd.sum()), 2),
                 "rework_history_usd": round(float(lots.rework_usd.sum()), 2),
                 "issue_cost_to_date_usd": round(sum(i["cost_to_date_usd"] for i in issues), 2),
                 "monthly_copq_now_usd": round(run_rate, 2), "monthly_scrap_now_usd": round(run_scrap, 2),
                 "monthly_reverify_now_usd": round(reverify, 2),
                 "monthly_scrap_saving_usd": round(sum(i["monthly_saving_if_fixed_usd"] * (i["scrap_to_date_usd"] / i["cost_to_date_usd"])
                                                       for i in issues if i["cost_to_date_usd"]), 2),
                 "monthly_copq_if_resolved_usd": round(after, 2), "monthly_saving_usd": round(savings, 2),
                 "monthly_copq_before_issues_usd": round(baseline, 2), "baseline_from": str(lots.day.min().date()),
                 "baseline_to": str((first_onset - timedelta(days=1)).date()), "gross_issue_estimate_usd": round(gross, 2),
                 "fix_cost_usd": round(fix, 2), "payback_months": payback,
                 "payback_days": round(30.4 * fix / savings, 1) if savings else None,
                 "net_over_horizon_usd": round(savings * months - fix, 2), "horizon_months": months,
                 "copq_reduction_pct": round(100 * savings / run_rate, 1) if run_rate else 0.0},
        "lines": lines, "history": history, "issues": issues, "projection": projection,
        "note": ("Scrap and rework costs are estimated: each lot's sampled defect rate is applied to the full lot "
                 "size. Part values, rework costs and fix costs are editable assumptions."),
    }
