import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { LineChart } from "../components/Charts.jsx";
import { Badge, Card, ErrorBox, Kpi, Loading } from "../components/ui.jsx";
import { NumberGrid, usd, usdShort } from "./FinOps.jsx";

const LINE_COLORS = { L1: "#c9ced6", L2: "#4aa3e0", L3: "#e2ac45" };
const TYPE_TONE = { material: "indigo", shift_spike: "red", drift: "amber", calibration: "neutral" };
const money = (v) => usd(v, 0);

function IssueCard({ i, months }) {
  const isDrift = i.type === "drift";
  return (
    <div className={`insight high ${i.type === "material" ? "material" : ""}`}>
      <div className="row wrap"><Badge tone={TYPE_TONE[i.type]}>{i.category}</Badge><strong>{i.title}</strong></div>
      <p className="muted small-text">Started {i.onset} · {i.days_active} days · {i.basis}</p>
      {i.trend?.length > 1 && (
        <LineChart height={150} yLabel="% parts" xEvery={2}
          series={[{ name: isDrift ? "out of spec %" : "defect rate %", color: "#4aa3e0",
            points: i.trend.map((t) => ({ x: t.week, y: t.rate_pct })) }]}
          refLines={i.rate_baseline_pct != null ? [{ y: i.rate_baseline_pct, label: "normal", color: "#737a85", dash: true }] : []} />
      )}
      <div className="qc-figs">
        <div><span>Cost so far</span><strong>{money(i.cost_to_date_usd)}</strong>
          <small>scrap {money(i.scrap_to_date_usd)} · rework {money(i.rework_to_date_usd)}</small></div>
        <div><span>Saving / month if resolved</span><strong className="text-green">{money(i.monthly_saving_if_fixed_usd)}</strong>
          <small>fix {money(i.fix_cost_usd)} · payback {i.payback_days == null ? "—" : `${i.payback_days} day${i.payback_days === 1 ? "" : "s"}`}</small></div>
        <div><span>Net over {months} months</span><strong>{usdShort(i.net_over_horizon_usd)}</strong><small>after fix cost</small></div>
      </div>
      <p className="small-text"><strong>Resolve by:</strong> {i.fix}</p>
      {i.risk && <p className="small-text text-amber">Risk: {i.risk}</p>}
    </div>
  );
}

export default function QualityCost({ can, notify }) {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const editable = can("qcost:edit");

  const load = useCallback(() => {
    api.qualityCost().then((d) => { setData(d); const { currency, ...s } = d.settings; setDraft(s); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true); setError("");
    try { await api.qualityCostSettings(draft, "Edited on Quality Cost page"); notify("Assumptions saved (audited)", "green"); load(); }
    catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  if (!data || !draft) return <div className="page"><ErrorBox error={error} />{!error && <Loading text="Costing the quality history…" />}</div>;
  const k = data.kpis;
  const { currency, ...current } = data.settings;
  const dirty = JSON.stringify(draft) !== JSON.stringify(current);
  const weeks = [...new Set(data.history.map((h) => h.week))].sort();
  const sumBy = (key) => weeks.map((w) => ({ x: w, y: Math.round(data.history.filter((h) => h.week === w).reduce((a, h) => a + h[key], 0)) }));
  const setNested = (group) => (v) => setDraft({ ...draft, [group]: v });

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Quality Cost Impact</h1>
          <p className="muted">What poor quality has cost the plant, where it came from, and what resolving today’s issues would save. All amounts in US dollars.</p>
        </div>
        <Badge tone="amber">History {data.window.from} → {data.window.to}</Badge>
      </header>
      <ErrorBox error={error} />

      <div className="kpi-row">
        <Kpi label={`Scrap + rework · ${data.window.days} days`} value={usdShort(k.copq_history_usd)} sub={`scrap ${usdShort(k.scrap_history_usd)} · rework ${usdShort(k.rework_history_usd)}`} />
        <Kpi label="Cost now / month" value={usdShort(k.monthly_copq_now_usd)} sub={`scrap ${usdShort(k.monthly_scrap_now_usd)} · re-verify ${usdShort(k.monthly_reverify_now_usd)}`} tone="red" />
        <Kpi label="If issues resolved" value={usdShort(k.monthly_copq_if_resolved_usd)} sub={`pre-issue level (${k.baseline_from} → ${k.baseline_to})`} />
        <Kpi label="Saving / month" value={usdShort(k.monthly_saving_usd)} sub={`−${k.copq_reduction_pct}% · scrap −${usdShort(k.monthly_scrap_saving_usd)}`} />
        <Kpi label="One-time fix cost" value={money(k.fix_cost_usd)} sub={`payback ${k.payback_days ?? "—"} days`} />
        <Kpi label={`Net · ${k.horizon_months} months`} value={usdShort(k.net_over_horizon_usd)} sub="savings − fix cost" />
      </div>

      <div className="grid-2">
        <Card title="History · weekly scrap + rework cost by line ($)">
          <LineChart yLabel="$ / week" xEvery={1}
            series={["L1", "L2", "L3"].map((ln) => ({ name: ln, color: LINE_COLORS[ln],
              points: data.history.filter((h) => h.line === ln).map((h) => ({ x: h.week, y: Math.round(h.copq_usd) })) }))} />
        </Card>
        <Card title="History · scrap vs rework, all lines ($)">
          <LineChart yLabel="$ / week" xEvery={1}
            series={[{ name: "scrap", color: "#f0605d", points: sumBy("scrap_usd") }, { name: "rework", color: "#4aa3e0", points: sumBy("rework_usd") }]} />
        </Card>
      </div>

      <Card title={`Cost by line · ${data.window.days} days`}>
        <table className="table compact">
          <thead><tr><th>Line</th><th>Part</th><th>Produced</th><th>Est. defective</th><th>Scrap</th><th>Rework</th><th>Total</th><th>Per month</th></tr></thead>
          <tbody>{data.lines.map((l) => (
            <tr key={l.line}><td><strong>{l.line}</strong></td><td>{l.part}</td><td>{l.produced.toLocaleString("en-US")}</td>
              <td>{l.est_defective.toLocaleString("en-US")}</td><td className="text-red">{money(l.scrap_usd)}</td><td>{money(l.rework_usd)}</td>
              <td><strong>{money(l.copq_usd)}</strong></td><td>{money(l.monthly_copq_usd)}</td></tr>))}
          </tbody>
        </table>
      </Card>

      <Card title="Open issues · history and saving if resolved" actions={<Badge>{data.issues.length} issues · cost so far {usdShort(k.issue_cost_to_date_usd)}</Badge>}>
        <div className="insights">{data.issues.map((i) => <IssueCard key={i.id} i={i} months={k.horizon_months} />)}</div>
        {!data.issues.length && <p className="muted">No open quality issues detected.</p>}
      </Card>

      <div className="grid-2">
        <Card title={`Projection · next ${k.horizon_months} months`} actions={k.payback_months != null && <Badge tone="green">fix cost recovered in month {k.payback_months}</Badge>}>
          <LineChart yLabel="$ / month" xEvery={2}
            series={[
              { name: "if unresolved", color: "#f0605d", points: data.projection.map((p) => ({ x: `M${String(p.month).padStart(2, "0")}`, y: Math.round(p.copq_if_unresolved_usd) })) },
              { name: "if resolved", color: "#43c690", points: data.projection.map((p) => ({ x: `M${String(p.month).padStart(2, "0")}`, y: Math.round(p.copq_if_resolved_usd) })) },
            ]} />
        </Card>
        <Card title="Projection · cumulative net saving ($)">
          <LineChart yLabel="$" xEvery={2}
            series={[{ name: "cumulative", color: "#43c690", points: data.projection.map((p) => ({ x: `M${String(p.month).padStart(2, "0")}`, y: Math.round(p.cumulative_net_saving_usd) })) }]}
            refLines={[{ y: 0, label: "break-even", color: "#737a85", dash: true }]} />
        </Card>
      </div>

      <Card title="Assumptions" actions={editable &&
        <button className="primary small" onClick={save} disabled={saving || !dirty}>{saving ? "Saving…" : dirty ? "Save & recalculate" : "Saved"}</button>}>
        <h4>Part value ($ lost per scrapped part)</h4>
        <NumberGrid fields={[["L1", "L1 · BD-220 Brake Disc", 0.5], ["L2", "L2 · GS-45 Gear Shaft", 0.5], ["L3", "L3 · PR-30 Piston Rod", 0.5]]}
                    values={draft.part_cost_usd} disabled={!editable} onChange={setNested("part_cost_usd")} />
        <h4>Rework cost ($ per reworked part)</h4>
        <NumberGrid fields={[["L1", "L1", 0.5], ["L2", "L2", 0.5], ["L3", "L3", 0.5]]}
                    values={draft.rework_cost_usd} disabled={!editable} onChange={setNested("rework_cost_usd")} />
        <h4>Share of defective parts scrapped (rest reworked)</h4>
        <NumberGrid fields={[["critical", "Critical (0–1)", 0.05], ["major", "Major (0–1)", 0.05], ["minor", "Minor (0–1)", 0.05]]}
                    values={draft.scrap_share} disabled={!editable} onChange={setNested("scrap_share")} />
        <h4>One-time cost to resolve ($)</h4>
        <NumberGrid fields={[["shift_spike", "Process / tooling issue", 50], ["material", "Raw-material issue", 50], ["drift", "Tool wear / drift", 50], ["calibration", "Gauge calibration", 10]]}
                    values={draft.fix_cost_usd} disabled={!editable} onChange={setNested("fix_cost_usd")} />
        <NumberGrid fields={[["reverify_cost_per_part_usd", "Re-verify cost $ / part", 0.05], ["projection_months", "Projection (months)"]]}
                    values={draft} disabled={!editable} onChange={setDraft} />
        <p className="muted small-text">{data.note} If issues are resolved, cost returns to the plant’s own level before the first issue started – never below it.
          {!editable && " Only the Plant Quality Head can change these assumptions."}</p>
      </Card>
    </div>
  );
}
