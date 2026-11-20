import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { LineChart } from "../components/Charts.jsx";
import { Badge, Card, ErrorBox, Kpi, Loading } from "../components/ui.jsx";
import { NumberGrid, usd, usdShort } from "./FinOps.jsx";

const money = (v) => usd(v, 0);

const FIELDS = [
  ["manual_minutes_per_report", "Manual minutes / report (before)"], ["ai_review_minutes_per_report", "Review minutes / report (with AI)"],
  ["quality_staff_rate_usd_hour", "Quality staff cost $ / hour", 0.05], ["audit_prep_hours_saved_per_month", "Audit-prep hours saved / month"],
  ["scrap_cost_per_part_usd", "Scrap cost $ / part", 0.1], ["defective_parts_contained_earlier_per_month", "Defective parts contained earlier / month"],
  ["customer_claims_avoided_per_year", "Customer claims avoided / year", 0.5], ["cost_per_customer_claim_usd", "Cost per customer claim $"],
  ["one_time_implementation_usd", "One-time implementation $"], ["horizon_months", "Evaluation horizon (months)"],
];

export default function CostBenefit({ can, notify }) {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const editable = can("cba:edit");

  const load = useCallback(() => {
    api.costBenefit().then((d) => { setData(d); setDraft(d.settings); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true); setError("");
    try { await api.finopsSettings("cba", { cba: draft }, "Edited on cost-benefit page"); notify("Assumptions saved (audited)", "green"); load(); }
    catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  if (!data || !draft) return <div className="page"><ErrorBox error={error} />{!error && <Loading text="Building the business case…" />}</div>;
  const d = data;
  const dirty = JSON.stringify(draft) !== JSON.stringify(d.settings);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Solution Cost-Benefit</h1>
          <p className="muted">Business case for the InspectIQ software itself – benefits against its full run cost (AI tokens, hosting, IT support). For IT and the Quality Manager. All amounts in US dollars.</p>
        </div>
        <Badge tone="amber">Assumptions – edit to match your plant</Badge>
      </header>
      <ErrorBox error={error} />

      <div className="kpi-row">
        <Kpi label="Net benefit / month" value={usdShort(d.net_monthly_usd)} sub={`${usdShort(d.benefit_monthly_usd)} benefit − ${usdShort(d.cost_monthly_usd)} cost`}
             tone={d.net_monthly_usd < 0 ? "red" : ""} />
        <Kpi label="Payback" value={d.payback_months == null ? "> horizon" : `${d.payback_months} months`} sub={`on ${usdShort(d.one_time_usd)} one-time`} />
        <Kpi label={`ROI · ${d.horizon_months} months`} value={d.roi_pct == null ? "—" : `${d.roi_pct}%`} sub={`benefit / cost ${d.benefit_cost_ratio}×`} />
        <Kpi label="Net over horizon" value={usdShort(d.net_over_horizon_usd)} sub={`${d.horizon_months} months`} />
        <Kpi label="Hours freed / month" value={Math.round(d.hours_saved_per_month).toLocaleString("en-IN")} sub={`≈ ${d.fte_equivalent} FTE · ${d.reports_per_month} reports`} />
      </div>

      <div className="grid-2">
        <Card title="Monthly benefits">
          <table className="table compact">
            <thead><tr><th>Benefit</th><th>How it is calculated</th><th>$ / month</th></tr></thead>
            <tbody>
              {d.benefits.map((b) => <tr key={b.item}><td><strong>{b.item}</strong></td><td className="muted small-text">{b.basis}</td><td className="nowrap"><strong>{money(b.monthly_usd)}</strong></td></tr>)}
              <tr><td><strong>Total benefit</strong></td><td /><td className="nowrap text-green"><strong>{money(d.benefit_monthly_usd)}</strong></td></tr>
            </tbody>
          </table>
        </Card>
        <Card title="Monthly run cost (from IT FinOps)" actions={<Badge>AI tokens = {d.token_share_of_run_cost_pct}% of run cost</Badge>}>
          <table className="table compact">
            <thead><tr><th>Cost</th><th>Owner</th><th>$ / month</th></tr></thead>
            <tbody>
              {d.costs.map((c) => <tr key={c.item}><td>{c.item}</td><td className="muted">{c.owner}</td><td className="nowrap">{usd(c.monthly_usd)}</td></tr>)}
              <tr><td><strong>Total run cost</strong></td><td /><td className="nowrap text-red"><strong>{usd(d.cost_monthly_usd)}</strong></td></tr>
              <tr><td>One-time implementation</td><td className="muted">Project</td><td className="nowrap">{money(d.one_time_usd)}</td></tr>
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Cumulative cash position ($)" actions={d.payback_months != null && <Badge tone="green">break-even in month {d.payback_months}</Badge>}>
        <LineChart yLabel="$" xEvery={3}
          series={[{ name: "cumulative", color: "#43c690", points: d.cumulative.map((c) => ({ x: `M${String(c.month).padStart(2, "0")}`, y: c.cumulative_usd })) }]}
          refLines={[{ y: 0, label: "break-even", color: "#737a85", dash: true }]} />
      </Card>

      <Card title="Assumptions" actions={editable &&
        <button className="primary small" onClick={save} disabled={saving || !dirty}>{saving ? "Saving…" : dirty ? "Save & recalculate" : "Saved"}</button>}>
        <NumberGrid fields={FIELDS} values={draft} disabled={!editable} onChange={setDraft} />
        <p className="muted small-text">{d.note} Report volume and run costs come from the IT FinOps settings.
          {!editable && " Only IT Support & FinOps can change these assumptions."}</p>
      </Card>
    </div>
  );
}
