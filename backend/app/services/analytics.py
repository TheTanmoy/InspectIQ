"""Deterministic analytics - every number in the app is computed here, never by the LLM.

KPIs, feature statistics (Cp/Cpk), Pareto, trends, SPC series, raw-material lot analysis and pattern detection.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.services.inspection_source import SyntheticSource

SEV_ORDER = {"minor": 0, "major": 1, "critical": 2}


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))) else round(float(x), n)


# ---------------------------------------------------------------- building blocks
def feature_stats(meas: pd.DataFrame) -> list[dict]:
    out = []
    if meas.empty:
        return out
    for (line, feature), g in meas.groupby(["line", "feature"], sort=True):
        lsl, usl = float(g.lsl.iloc[0]), float(g.usl.iloc[0])
        mean, std = float(g.value.mean()), float(g.value.std(ddof=1)) if len(g) > 1 else 0.0
        one_sided_upper = lsl == 0.0  # e.g. runout, roughness: only an upper limit matters
        if std > 0:
            cp = None if one_sided_upper else (usl - lsl) / (6 * std)
            cpk = (usl - mean) / (3 * std) if one_sided_upper else min(usl - mean, mean - lsl) / (3 * std)
        else:
            cp = cpk = None
        out.append({"line": line, "feature": feature, "unit": g.unit.iloc[0], "station": g.station.iloc[0],
                    "gauge_id": g.gauge_id.iloc[0], "n": int(len(g)), "mean": _r(mean), "std": _r(std, 5),
                    "min": _r(g.value.min()), "max": _r(g.value.max()), "nominal": _r(g.nominal.iloc[0]),
                    "lsl": _r(lsl), "usl": _r(usl), "cp": _r(cp, 2), "cpk": _r(cpk, 2),
                    "out_of_spec": int((~g.in_spec.astype(bool)).sum())})
    return out


def pareto(det: pd.DataFrame, codes: list[dict]) -> list[dict]:
    if det.empty:
        return []
    names = {c["code"]: c["name"] for c in codes}
    counts = det.groupby("defect_code").size().sort_values(ascending=False)
    total = int(counts.sum())
    cum, out = 0, []
    for code, n in counts.items():
        cum += int(n)
        out.append({"defect_code": code, "name": names.get(code, code), "count": int(n),
                    "pct": round(100 * n / total, 1), "cum_pct": round(100 * cum / total, 1)})
    return out


def kpis(meas: pd.DataFrame, det: pd.DataFrame) -> dict:
    inspected = int(meas.part_serial.nunique()) if not meas.empty else 0
    oos_parts = set(meas.loc[~meas.in_spec.astype(bool), "part_serial"]) if not meas.empty else set()
    det_parts = set(det.part_serial) if not det.empty else set()
    defective = len(oos_parts | det_parts)
    crit = int((det.severity == "critical").sum()) if not det.empty else 0
    return {"parts_inspected": inspected, "defective_parts": defective,
            "defect_rate_pct": round(100 * defective / inspected, 2) if inspected else 0.0,
            "first_pass_yield_pct": round(100 * (inspected - defective) / inspected, 2) if inspected else 0.0,
            "camera_detections": int(len(det)), "out_of_spec_parts": len(oos_parts), "critical_defects": crit}


# ---------------------------------------------------------------- dashboard
def overview(store: SyntheticSource, days: int = 30, line: str = "") -> dict:
    end = store.lots().shift_end.max()
    start = end - timedelta(days=days)
    meas, det, lots = store.measurements(), store.detections(), store.lots()
    meas = meas[meas.ts >= start]
    det = det[det.ts >= start]
    lots = lots[lots.shift_end >= start]
    if line:
        meas, det, lots = meas[meas.line == line], det[det.line == line], lots[lots.line == line]

    parts_day = meas.assign(day=meas.ts.dt.date).groupby(["line", "day"]).part_serial.nunique()
    det_day = det.assign(day=det.ts.dt.date).groupby(["line", "day"]).size()
    trend_df = pd.DataFrame({"parts": parts_day, "defects": det_day}).fillna(0).reset_index()
    trend_df["per_100"] = (100 * trend_df.defects / trend_df.parts.replace(0, np.nan)).round(2).fillna(0)
    trend = {}
    for ln, g in trend_df.groupby("line"):
        trend[ln] = [{"day": str(r.day), "defects": int(r.defects), "parts": int(r.parts), "per_100": float(r.per_100)}
                     for r in g.itertuples()]

    parts_shift = meas.groupby(["line", "shift"]).part_serial.nunique()
    det_shift = det.groupby(["line", "shift"]).size()
    shift_df = pd.DataFrame({"parts": parts_shift, "defects": det_shift}).fillna(0).reset_index()
    shift_cmp = [{"line": r.line, "shift": r.shift, "parts": int(r.parts), "defects": int(r.defects),
                  "per_100": round(100 * r.defects / r.parts, 2) if r.parts else 0}
                 for r in shift_df.itertuples()]

    return {"window": {"from": str(start), "to": str(end), "days": days, "line": line or "all"},
            "kpis": kpis(meas, det), "pareto": pareto(det, store.defect_codes()),
            "features": feature_stats(meas), "trend": trend, "shift_comparison": shift_cmp,
            "lots": int(len(lots)), "materials": material_summary(store, set(lots.material_lot.dropna())
                                                                   if "material_lot" in lots else None, line),
            "insights": detect_patterns(store)}


def spc_series(store: SyntheticSource, line: str, feature: str, days: int = 60) -> dict:
    meas = store.measurements()
    g = meas[(meas.line == line) & (meas.feature == feature)]
    if g.empty:
        return {"line": line, "feature": feature, "points": []}
    end = g.ts.max()
    g = g[g.ts >= end - timedelta(days=days)]
    daily = g.groupby(g.ts.dt.date).value.agg(["mean", "count"]).reset_index()
    base = daily.head(max(5, len(daily) // 2))  # first half = baseline for control limits
    center, sd = float(base["mean"].mean()), float(base["mean"].std(ddof=1))
    return {"line": line, "feature": feature, "unit": g.unit.iloc[0],
            "lsl": float(g.lsl.iloc[0]), "usl": float(g.usl.iloc[0]), "nominal": float(g.nominal.iloc[0]),
            "center": _r(center), "ucl": _r(center + 3 * sd), "lcl": _r(center - 3 * sd),
            "points": [{"day": str(r.ts), "mean": _r(r.mean), "n": int(r.count)} for r in daily.itertuples()]}


# ---------------------------------------------------------------- raw material
def _parts_with_material(store: SyntheticSource) -> pd.DataFrame:
    lots = store.lots()
    parts = store.measurements().drop_duplicates("part_serial")[["part_serial", "line", "shift", "lot", "ts"]]
    if "material_lot" not in lots:
        return parts.assign(material_lot="")
    return parts.merge(lots[["lot", "material_lot"]], on="lot", how="left")


def material_summary(store: SyntheticSource, used: set | None = None, line: str = "") -> list[dict]:
    """Defect rate per raw-material lot (heat), with its certificate check - newest first."""
    mats = store.materials()
    if mats.empty:
        return []
    parts = _parts_with_material(store)
    det = store.detections().merge(parts[["part_serial", "material_lot"]], on="part_serial", how="left")
    names = {c["code"]: c["name"] for c in store.defect_codes()}
    out = []
    for r in mats.sort_values("first_used", ascending=False).itertuples():
        if (line and r.line != line) or (used is not None and r.material_lot not in used):
            continue
        n = int((parts.material_lot == r.material_lot).sum())
        if not n:
            continue
        dg = det[det.material_lot == r.material_lot]
        top = dg.defect_code.value_counts()
        info = store.material(r.material_lot)
        out.append({"material_lot": r.material_lot, "line": r.line, "supplier": r.supplier, "heat_number": r.heat_number,
                    "first_used": r.first_used, "incoming_result": r.incoming_result, "deviation_ref": r.deviation_ref,
                    "deviations": info["deviations"], "parts": n, "defects": int(len(dg)),
                    "per_100": round(100 * len(dg) / n, 2),
                    "top_defect": names.get(top.index[0], top.index[0]) if len(top) else None,
                    "top_defect_count": int(top.iloc[0]) if len(top) else 0})
    return out


def _material_patterns(store: SyntheticSource, names: dict) -> list[dict]:
    """A raw-material cause shows up as a defect that is elevated on ONE heat, on every shift that ran it.
    (A process cause - like the L1 mold change - is limited to one shift, so it is not reported here.)"""
    if store.materials().empty:
        return []
    parts = _parts_with_material(store).dropna(subset=["material_lot"])
    det = store.detections().merge(parts[["part_serial", "material_lot"]], on="part_serial", how="inner")
    out = []
    for line, lp in parts.groupby("line"):
        ld = det[det.line == line]
        for ml, mp in lp.groupby("material_lot"):
            if len(mp) < 100:
                continue
            other = lp[lp.material_lot != ml]
            md, od = ld[ld.material_lot == ml], ld[ld.material_lot != ml]
            for code, cg in md.groupby("defect_code"):
                rate = 100 * len(cg) / len(mp)
                base = 100 * int((od.defect_code == code).sum()) / max(len(other), 1)
                if len(cg) < 8 or rate < 2.5 * max(base, 0.3):
                    continue
                by_shift = {}
                for sh, sp in mp.groupby("shift"):
                    if len(sp) >= 20:
                        by_shift[sh] = round(100 * int((cg["shift"] == sh).sum()) / len(sp), 2)
                if len(by_shift) < 2 or min(by_shift.values()) < 1.8 * max(base, 0.3):
                    continue  # not consistent across shifts -> more likely a process/shift cause
                info = store.material(ml) or {}
                cert = "; ".join(info.get("deviations", [])) or "certificate within spec"
                dev = f", accepted under deviation {info['deviation_ref']}" if info.get("deviation_ref") else ""
                out.append({
                    "id": f"MAT-{line}-{ml}-{code}", "type": "material", "severity": "high",
                    "line": line, "material_lot": ml, "defect_code": code,
                    "title": f"{names.get(code, code)} linked to raw-material lot {ml} on {line}",
                    "metrics": {"per_100_this_lot": round(rate, 2), "per_100_other_lots": round(base, 2),
                                "ratio": round(rate / max(base, 0.01), 1), "count": int(len(cg)),
                                "parts": int(len(mp)), "per_100_by_shift": by_shift},
                    "detail": (f"Parts made from {ml} (heat {info.get('heat_number', '?')}, {info.get('supplier', '?')}) show "
                               f"{rate:.2f} {names.get(code, code).lower()} per 100 parts vs {base:.2f} on other material "
                               f"lots ({len(cg)} detections in {len(mp)} parts), on every shift that used it."),
                    "possible_cause": f"Raw material: mill certificate {cert}{dev}.",
                })
    return out


# ---------------------------------------------------------------- pattern detection (insights)
def detect_patterns(store: SyntheticSource, recent_days: int = 14) -> list[dict]:
    insights = []
    meas, det, maint = store.measurements(), store.detections(), store.maintenance()
    end = meas.ts.max()
    recent_start = end - timedelta(days=recent_days)
    prior_start = recent_start - timedelta(days=30)
    names = {c["code"]: c["name"] for c in store.defect_codes()}

    parts = meas.drop_duplicates("part_serial")[["part_serial", "line", "shift", "ts"]]

    # 1. shift-specific defect spikes (recent vs prior period, same line + shift)
    for (line, shift), pg in parts.groupby(["line", "shift"]):
        rec_parts = int((pg.ts >= recent_start).sum())
        pri_parts = int(((pg.ts >= prior_start) & (pg.ts < recent_start)).sum())
        if rec_parts < 50 or pri_parts < 50:
            continue
        dg = det[(det.line == line) & (det["shift"] == shift)]
        for code, cg in dg.groupby("defect_code"):
            rec = int((cg.ts >= recent_start).sum())
            pri = int(((cg.ts >= prior_start) & (cg.ts < recent_start)).sum())
            rec_rate, pri_rate = 100 * rec / rec_parts, 100 * pri / pri_parts
            if rec >= 8 and rec_rate >= 2.5 * max(pri_rate, 0.3):
                ev = maint[(maint.line == line) & (maint.ts >= recent_start - timedelta(days=4)) & (maint.ts <= end)]
                link = ev.iloc[-1].to_dict() if not ev.empty else None
                insights.append({
                    "id": f"SPIKE-{line}-{shift}-{code}", "type": "shift_spike", "severity": "high",
                    "line": line, "shift": shift, "defect_code": code,
                    "title": f"{names.get(code, code)} spike on {line} shift {shift}",
                    "metrics": {"recent_per_100": round(rec_rate, 2), "prior_per_100": round(pri_rate, 2),
                                "recent_count": rec, "ratio": round(rec_rate / max(pri_rate, 0.01), 1),
                                "recent_days": recent_days},
                    "detail": (f"{names.get(code, code)} on {line} shift {shift} is {rec_rate:.2f} per 100 parts in the "
                               f"last {recent_days} days vs {pri_rate:.2f} in the 30 days before ({rec} detections)."),
                    "possible_cause": (f"Started after maintenance on {link['ts']:%Y-%m-%d %H:%M}: {link['event']} "
                                       f"({link['station']}).") if link else None,
                })

    # a defect rising on every shift of a line is not shift-specific (see raw-material check below)
    shifts_per_line = parts.groupby("line")["shift"].nunique().to_dict()
    spiked = {}
    for i in insights:
        spiked.setdefault((i["line"], i["defect_code"]), []).append(i)
    insights = [i for (ln, _), group in spiked.items() if len(group) < shifts_per_line.get(ln, 3) for i in group]

    # 2. measurement drift towards a spec limit
    for (line, feature), g in meas[meas.ts >= end - timedelta(days=20)].groupby(["line", "feature"]):
        daily = g.groupby(g.ts.dt.normalize()).value.mean()
        if len(daily) < 10:
            continue
        x = (daily.index - daily.index[0]).days.values.astype(float)
        slope, intercept = np.polyfit(x, daily.values, 1)
        usl, lsl = float(g.usl.iloc[0]), float(g.lsl.iloc[0])
        sigma = float(g.value.std(ddof=1))
        moved = slope * x[-1]
        current = intercept + slope * x[-1]
        if abs(moved) < 1.2 * sigma or sigma == 0:
            continue
        limit = usl if slope > 0 else lsl
        days_to_limit = (limit - current) / slope if slope else None
        recent = g[g.ts >= end - timedelta(days=3)]
        rs = float(recent.value.std(ddof=1)) or sigma
        cpk_now = min(usl - recent.value.mean(), recent.value.mean() - lsl) / (3 * rs)
        insights.append({
            "id": f"DRIFT-{line}-{feature}", "type": "drift", "severity": "high" if (days_to_limit or 99) < 14 else "medium",
            "line": line, "feature": feature, "station": g.station.iloc[0],
            "title": f"{feature} drifting {'up' if slope > 0 else 'down'} on {line} {g.station.iloc[0]}",
            "metrics": {"slope_per_day": _r(slope, 5), "current_mean": _r(current), "limit": _r(limit),
                        "days_to_limit": _r(max(days_to_limit, 0), 1) if days_to_limit is not None else None,
                        "cpk_last_3_days": _r(cpk_now, 2), "out_of_spec_last_3_days": int((~recent.in_spec.astype(bool)).sum())},
            "detail": (f"Daily mean of {feature} moved {moved:+.4f} {g.unit.iloc[0]} in 20 days "
                       f"(now {current:.4f}, limit {limit}). Cpk over the last 3 days is {cpk_now:.2f}."),
            "possible_cause": "Gradual change like this usually points to tool or wheel wear.",
        })

    # 3. raw-material lot linked to a defect
    insights += _material_patterns(store, names)

    # 4. gauge calibration
    today = end.date()
    for gauge in store.gauges():
        due = datetime.fromisoformat(gauge["calibration_due"]).date()
        if due < today:
            insights.append({"id": f"CAL-{gauge['gauge_id']}", "type": "calibration", "severity": "high",
                             "line": gauge["line"], "title": f"Gauge {gauge['gauge_id']} calibration expired",
                             "metrics": {"calibration_due": str(due), "days_overdue": (today - due).days},
                             "detail": f"{gauge['type']} {gauge['gauge_id']} ({gauge['feature']}) was due for calibration "
                                       f"on {due}. Measurements taken with it since then are not reliable.",
                             "possible_cause": None})
        elif (due - today).days <= 7:
            insights.append({"id": f"CAL-{gauge['gauge_id']}", "type": "calibration", "severity": "low",
                             "line": gauge["line"], "title": f"Gauge {gauge['gauge_id']} calibration due soon",
                             "metrics": {"calibration_due": str(due), "days_left": (due - today).days},
                             "detail": f"{gauge['gauge_id']} is due for calibration on {due}.", "possible_cause": None})

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(insights, key=lambda i: order[i["severity"]])
