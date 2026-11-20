import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { HBars, LineChart } from "../components/Charts.jsx";
import { Badge, Card, ErrorBox, Kpi, Loading, fmtDate } from "../components/ui.jsx";

export const usd = (v, d = 2) => `${v < 0 ? "-" : ""}$${Math.abs(Number(v || 0)).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
/** compact dollars for KPI tiles: $412, $5.6k, $1.2M */
export const usdShort = (v) => {
  const a = Math.abs(v || 0), sign = v < 0 ? "-" : "";
  return a >= 1e6 ? `${sign}$${(a / 1e6).toFixed(2)}M` : a >= 1e4 ? `${sign}$${(a / 1e3).toFixed(1)}k` : `${sign}$${Math.round(a).toLocaleString("en-US")}`;
};
const num = (v) => Number(v || 0).toLocaleString("en-IN");

/** Small editable number grid used by the FinOps and Cost-Benefit pages. */
export function NumberGrid({ fields, values, onChange, disabled }) {
  return (
    <div className="num-grid">
      {fields.map(([key, label, step = 1]) => (
        <label key={key}>{label}
          <input type="number" min="0" step={step} value={values[key] ?? 0} disabled={disabled}
                 onChange={(e) => onChange({ ...values, [key]: e.target.value === "" ? 0 : Number(e.target.value) })} />
        </label>
      ))}
    </div>
  );
}

const VOLUME_FIELDS = [["reports_per_day", "Reports / day"], ["assistant_chats_per_day", "Assistant chats / day"],
  ["insight_explains_per_day", "Insight explains / day"], ["rewrites_per_day", "Section rewrites / day"],
  ["working_days_per_month", "Working days / month"]];
const RUN_FIELDS = [["hosting_usd", "Hosting $ / month"], ["monitoring_backup_usd", "Monitoring & backup $ / month"],
  ["it_support_hours", "IT support hours / month"], ["it_hourly_rate_usd", "IT hourly rate $"],
  ["model_prompt_review_hours", "Prompt & model review h / month"]];

export default function FinOps({ can, notify }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const editable = can("finops:edit");

  const load = useCallback(() => {
    api.finopsUsage(days).then((d) => {
      setData(d);
      const s = d.settings;
      setDraft({ monthly_ai_budget_usd: s.monthly_ai_budget_usd, volumes: s.volumes,
        run_costs: s.run_costs, pricing: s.pricing });
    }).catch((e) => setError(e.message));
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true); setError("");
    try { await api.finopsSettings("finops", draft, "Edited on FinOps page"); notify("FinOps settings saved (audited)", "green"); load(); }
    catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  if (!data || !draft) return <div className="page"><ErrorBox error={error} />{!error && <Loading text="Loading AI usage…" />}</div>;
  const k = data.kpis, p = data.projection, sm = data.support_maintenance;
  const overBudget = p.budget_used_pct != null && p.budget_used_pct > 100;
  const setPrice = (model, key, v) => setDraft({ ...draft, pricing: { ...draft.pricing, [model]: { ...draft.pricing[model], [key]: v } } });

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>AI Cost &amp; Operations</h1>
          <p className="muted">Token usage, cost and the support &amp; maintenance run cost of InspectIQ – for IT Support and FinOps. All amounts in US dollars.</p>
        </div>
        <div className="row">
          <Badge tone="indigo">Primary: {data.models.primary}</Badge>
          {data.models.fallback && <Badge>Fallback: {data.models.fallback}</Badge>}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}
          </select>
        </div>
      </header>
      <ErrorBox error={error} />

      <div className="kpi-row">
        <Kpi label="AI calls" value={num(k.calls)} sub={`${k.measured_calls} with measured tokens`} />
        <Kpi label="Tokens in / out" value={`${(k.input_tokens / 1000).toFixed(1)}k / ${((k.output_tokens + k.thinking_tokens) / 1000).toFixed(1)}k`}
             sub={k.thinking_tokens ? `incl. ${num(k.thinking_tokens)} thinking` : "input / output"} />
        <Kpi label="Spend in window" value={usd(k.cost_usd, 4)} sub={`last ${days} day${days > 1 ? "s" : ""}`} />
        <Kpi label="Projected / month" value={usd(p.monthly_usd)} sub={`${p.budget_used_pct ?? "—"}% of ${usd(p.budget_usd, 0)} budget`}
             tone={overBudget ? "red" : p.budget_used_pct > 80 ? "amber" : ""} />
        <Kpi label="Fallback rate" value={`${k.fallback_rate_pct}%`} sub="answered by fallback model" tone={k.fallback_rate_pct > 30 ? "amber" : ""} />
        <Kpi label="Error rate" value={`${k.error_rate_pct}%`} sub={`avg latency ${(k.avg_latency_ms / 1000).toFixed(1)} s`} tone={k.error_rate_pct > 10 ? "red" : ""} />
      </div>
      {overBudget && <div className="banner">Projected AI spend is above the monthly budget of {usd(p.budget_usd)}. Review volumes, prompt size or model choice.</div>}

      <div className="grid-2">
        <Card title="Daily AI spend (USD)">
          <LineChart yLabel="USD" series={[{ name: "spend", color: "#4aa3e0", points: data.daily.map((d) => ({ x: d.day, y: d.cost_usd })) }]} />
        </Card>
        <Card title="Spend by purpose">
          {data.by_purpose.length ? <HBars data={data.by_purpose.map((b) => ({ label: b.label, value: Number(b.cost_usd.toFixed(4)), tone: "blue" }))} unit=" $" />
            : <p className="muted">No AI calls in this window.</p>}
          <table className="table compact" style={{ marginTop: "1rem" }}>
            <thead><tr><th>Purpose</th><th>Calls</th><th>Tokens in</th><th>Tokens out</th><th>Avg latency</th><th>Errors</th></tr></thead>
            <tbody>{data.by_purpose.map((b) => (
              <tr key={b.purpose}><td>{b.label}</td><td>{b.calls}</td><td>{num(b.input_tokens)}</td>
                <td>{num(b.output_tokens + b.thinking_tokens)}</td><td>{(b.avg_latency_ms / 1000).toFixed(1)} s</td><td>{b.errors || "—"}</td></tr>))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="grid-2">
        <Card title={`Monthly token forecast · priced at ${p.priced_at}`} actions={<Badge>{usd(p.annual_usd)} / year</Badge>}>
          <table className="table compact">
            <thead><tr><th>Use</th><th>Calls / month</th><th>Avg tokens in / out</th><th>Basis</th><th>$ / call</th><th>$ / month</th></tr></thead>
            <tbody>{p.lines.map((l) => (
              <tr key={l.purpose}><td>{l.label}</td><td>{num(l.calls_per_month)}</td><td>{num(l.avg_input_tokens)} / {num(l.avg_output_tokens)}</td>
                <td><Badge tone={l.basis.startsWith("measured") ? "green" : "neutral"}>{l.basis}</Badge></td>
                <td>{usd(l.cost_per_call_usd, 4)}</td><td><strong>{usd(l.monthly_usd)}</strong></td></tr>))}
            </tbody>
          </table>
          <h4>Expected volume</h4>
          <NumberGrid fields={VOLUME_FIELDS} values={draft.volumes} disabled={!editable} onChange={(v) => setDraft({ ...draft, volumes: v })} />
        </Card>

        <Card title="Support & maintenance run cost" actions={<Badge tone="indigo">{usd(sm.monthly_usd)} / month</Badge>}>
          <table className="table compact">
            <thead><tr><th>Item</th><th>Owner</th><th>$ / month</th></tr></thead>
            <tbody>{sm.items.map((i) => <tr key={i.item}><td>{i.item}</td><td className="muted">{i.owner}</td><td className="nowrap"><strong>{usd(i.monthly_usd)}</strong></td></tr>)}
              <tr><td><strong>Total</strong></td><td /><td className="nowrap"><strong>{usd(sm.monthly_usd)}</strong> <span className="muted small-text">({usd(sm.annual_usd, 0)} / year)</span></td></tr>
            </tbody>
          </table>
          <h4>Run-cost assumptions</h4>
          <NumberGrid fields={RUN_FIELDS} values={draft.run_costs} disabled={!editable} onChange={(v) => setDraft({ ...draft, run_costs: v })} />
        </Card>
      </div>

      <Card title="Model pricing (USD per 1M tokens)" actions={editable &&
        <button className="primary small" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>}>
        <p className="muted small-text" style={{ marginTop: 0 }}>{data.settings.pricing_note} Thinking tokens are billed as output.</p>
        <div className="table-wrap">
          <table className="table compact">
            <thead><tr><th>Model</th><th>Input $ / 1M</th><th>Output $ / 1M</th></tr></thead>
            <tbody>{Object.entries(draft.pricing).map(([model, pr]) => (
              <tr key={model}><td className="mono">{model}</td>
                <td><input type="number" min="0" step="0.01" value={pr.input_per_m} disabled={!editable} onChange={(e) => setPrice(model, "input_per_m", Number(e.target.value))} /></td>
                <td><input type="number" min="0" step="0.01" value={pr.output_per_m} disabled={!editable} onChange={(e) => setPrice(model, "output_per_m", Number(e.target.value))} /></td></tr>))}
            </tbody>
          </table>
        </div>
        <NumberGrid fields={[["monthly_ai_budget_usd", "Monthly AI budget $", 1]]}
                    values={draft} disabled={!editable} onChange={(v) => setDraft({ ...draft, ...v })} />
        {!editable && <p className="muted small-text">Read-only for your role – IT Support & FinOps can change prices and budgets.</p>}
      </Card>

      <Card title="Recent AI calls">
        <div className="table-wrap">
          <table className="table compact">
            <thead><tr><th>Time</th><th>User</th><th>Purpose</th><th>Model</th><th>In</th><th>Out</th><th>Latency</th><th>Cost</th><th>Status</th></tr></thead>
            <tbody>{data.recent.map((r, i) => (
              <tr key={i} className={r.ok ? "" : "row-danger"}>
                <td className="nowrap">{fmtDate(r.ts)}</td><td>{r.username}</td><td>{r.purpose}</td><td className="mono">{r.model}</td>
                <td>{num(r.input_tokens)}{r.estimated ? "*" : ""}</td><td>{num(r.output_tokens + r.thinking_tokens)}</td>
                <td>{(r.latency_ms / 1000).toFixed(1)} s</td><td>{usd(r.cost_usd, 5)}</td>
                <td>{r.ok ? <Badge tone="green">ok</Badge> : <Badge tone="red" title={r.error}>failed</Badge>}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
        <p className="muted small-text">* estimated from text length (provider reported no usage). Calls before token tracking was added show 0 tokens.</p>
      </Card>
    </div>
  );
}
