import { useEffect, useState } from "react";
import { api } from "../api";
import { HBars, LineChart, ParetoChart } from "../components/Charts.jsx";
import Markdown from "../components/Markdown.jsx";
import { Badge, Card, ErrorBox, Kpi, Loading } from "../components/ui.jsx";

const LINE_COLORS = { L1: "#c9ced6", L2: "#4aa3e0", L3: "#e2ac45" };

function MaterialCard({ materials }) {
  const [open, setOpen] = useState(false);
  if (!materials?.length) return null;
  const flagged = materials.filter((m) => m.deviations.length);
  const shown = open ? materials : materials.slice(0, 8);
  return (
    <Card title="Raw material lots · defect rate by heat" actions={
      <>
        {flagged.length > 0 && <Badge tone="red">{flagged.length} off-spec heat{flagged.length > 1 ? "s" : ""}</Badge>}
        <Badge>{materials.length} lots</Badge>
      </>}>
      <p className="muted small-text" style={{ marginTop: 0, marginBottom: ".9rem" }}>
        Each production lot is traced to the bar or melt heat it was made from. A defect that is high on one heat across
        every shift points to the material, not the process.
      </p>
      <div className="grid-2">
        <HBars data={materials.slice(0, 10).map((m) => ({
          label: `${m.material_lot} · ${m.supplier.replace(" (synthetic)", "")}`, value: m.per_100,
          tone: m.deviations.length ? "red" : m.per_100 > 3 ? "amber" : "" }))} />
        <div className="table-wrap">
          <table className="table compact">
            <thead><tr><th>Lot</th><th>Heat</th><th>Used from</th><th>Certificate</th><th>/100</th></tr></thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.material_lot} className={m.deviations.length ? "row-danger" : ""}>
                  <td><span className="mono">{m.material_lot}</span><div className="muted small-text">{m.supplier.replace(" (synthetic)", "")}</div></td>
                  <td className="mono">{m.heat_number}</td>
                  <td className="nowrap">{m.first_used}</td>
                  <td>
                    {m.deviations.length
                      ? <><Badge tone="red">off-spec</Badge><div className="small-text text-red">{m.deviations.join("; ")}</div>
                          {m.deviation_ref && <div className="muted small-text">deviation {m.deviation_ref}</div>}</>
                      : <Badge tone="green">in spec</Badge>}
                  </td>
                  <td><strong>{m.per_100}</strong>{m.top_defect && <div className="muted small-text">{m.top_defect} ×{m.top_defect_count}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {materials.length > 8 && <button className="link small-text" onClick={() => setOpen(!open)}>{open ? "Show fewer" : `Show all ${materials.length}`}</button>}
        </div>
      </div>
    </Card>
  );
}

export default function Dashboard({ can }) {
  const [days, setDays] = useState(30);
  const [line, setLine] = useState("");
  const [data, setData] = useState(null);
  const [spcSel, setSpcSel] = useState("L3|rod_diameter");
  const [spc, setSpc] = useState(null);
  const [explain, setExplain] = useState(null);
  const [explaining, setExplaining] = useState(false);
  const [comp, setComp] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    api.overview(days, line).then(setData).catch((e) => setError(e.message));
  }, [days, line]);

  useEffect(() => {
    const [l, f] = spcSel.split("|");
    api.spc(l, f, 60).then(setSpc).catch((e) => setError(e.message));
  }, [spcSel]);

  useEffect(() => {
    if (can("compliance:view")) api.complianceSummary().then(setComp).catch(() => {});
  }, [can]);

  const runExplain = async () => {
    setExplaining(true);
    try { setExplain(await api.explainInsights()); } catch (e) { setError(e.message); } finally { setExplaining(false); }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Quality Dashboard</h1>
          <p className="muted">Defect trends, capability and AI-detected patterns across all lines.</p>
        </div>
        <div className="row">
          <select value={line} onChange={(e) => setLine(e.target.value)}>
            <option value="">All lines</option><option value="L1">L1 · Brake Disc</option>
            <option value="L2">L2 · Gear Shaft</option><option value="L3">L3 · Piston Rod</option>
          </select>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 14, 30, 60].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>
      </header>
      <ErrorBox error={error} />
      {!data ? <Loading text="Crunching inspection data…" /> : (
        <>
          <div className="kpi-row">
            <Kpi label="Parts inspected" value={data.kpis.parts_inspected.toLocaleString()} sub={`${data.lots} lots`} />
            <Kpi label="Defect rate" value={`${data.kpis.defect_rate_pct}%`} tone={data.kpis.defect_rate_pct > 3 ? "amber" : ""} />
            <Kpi label="First-pass yield" value={`${data.kpis.first_pass_yield_pct}%`} />
            <Kpi label="Camera detections" value={data.kpis.camera_detections} />
            <Kpi label="Critical defects" value={data.kpis.critical_defects} tone={data.kpis.critical_defects ? "red" : ""} />
          </div>

          <Card title="AI Insights · patterns detected" actions={
            <button className="primary small" onClick={runExplain} disabled={explaining}>{explaining ? "Explaining…" : "Explain with AI"}</button>}>
            <div className="insights">
              {data.insights.map((i) => (
                <div key={i.id} className={`insight ${i.severity} ${i.type === "material" ? "material" : ""}`}>
                  <div className="row wrap"><Badge tone={i.severity === "high" ? "red" : i.severity === "medium" ? "amber" : "neutral"}>{i.severity}</Badge>
                    {i.type === "material" && <Badge tone="indigo">raw material</Badge>}
                    <strong>{i.title}</strong></div>
                  <p>{i.detail}</p>
                  {i.possible_cause && <p className="muted small-text">Likely cause: {i.possible_cause}</p>}
                </div>
              ))}
              {!data.insights.length && <p className="muted">No significant patterns detected.</p>}
            </div>
            {explain && (
              <div className="explain">
                <Markdown text={explain.text} />
                <div className="row wrap">
                  <Badge>{explain.mode}</Badge>
                  {explain.guardrails.map((g, i) => <Badge key={i} tone={g.status === "pass" ? "green" : "amber"}>{g.check}: {g.detail}</Badge>)}
                </div>
              </div>
            )}
          </Card>

          <MaterialCard materials={data.materials} />

          <div className="grid-2">
            <Card title="Defects per 100 parts (daily)">
              <LineChart yLabel="per 100 parts"
                series={Object.entries(data.trend).map(([ln, pts]) => ({
                  name: ln, color: LINE_COLORS[ln], points: pts.map((p) => ({ x: p.day, y: p.per_100 })) }))} />
            </Card>
            <Card title="Defect Pareto">
              <ParetoChart data={data.pareto.map((p) => ({ label: p.name, value: p.count, cum: p.cum_pct }))} />
            </Card>
          </div>

          <div className="grid-2">
            <Card title="SPC – daily mean vs limits" actions={
              <select value={spcSel} onChange={(e) => setSpcSel(e.target.value)}>
                {data.features.map((f) => <option key={`${f.line}|${f.feature}`} value={`${f.line}|${f.feature}`}>{f.line} · {f.feature}</option>)}
              </select>}>
              {spc ? (
                <LineChart yLabel={spc.unit}
                  series={[{ name: `${spc.line} ${spc.feature}`, color: "#4aa3e0", points: spc.points.map((p) => ({ x: p.day, y: p.mean })) }]}
                  refLines={[
                    { y: spc.usl, label: "USL", color: "#f0605d" }, { y: spc.ucl, label: "UCL", color: "#e2ac45", dash: true },
                    { y: spc.center, label: "CL", color: "#737a85", dash: true }, { y: spc.lcl, label: "LCL", color: "#e2ac45", dash: true },
                    ...(spc.lsl > 0 ? [{ y: spc.lsl, label: "LSL", color: "#f0605d" }] : []),
                  ]} />
              ) : <Loading />}
            </Card>
            <Card title="Defects per 100 parts by shift">
              <HBars data={data.shift_comparison.map((s) => ({
                label: `${s.line} · shift ${s.shift}`, value: s.per_100, tone: s.per_100 > 4 ? "red" : s.per_100 > 2.5 ? "amber" : "" }))} />
            </Card>
          </div>

          <div className="grid-2">
            <Card title="Process capability (Cpk)">
              <div className="table-wrap">
                <table className="table compact">
                  <thead><tr><th>Line</th><th>Feature</th><th>Mean</th><th>LSL</th><th>USL</th><th>Cpk</th><th>OOS</th></tr></thead>
                  <tbody>
                    {data.features.map((f) => (
                      <tr key={`${f.line}${f.feature}`} onClick={() => setSpcSel(`${f.line}|${f.feature}`)} className="clickable-row">
                        <td>{f.line}</td><td>{f.feature}</td><td>{f.mean}</td><td>{f.lsl}</td><td>{f.usl}</td>
                        <td><Badge tone={f.cpk == null ? "neutral" : f.cpk < 1 ? "red" : f.cpk < 1.33 ? "amber" : "green"}>{f.cpk ?? "—"}</Badge></td>
                        <td>{f.out_of_spec || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            {comp && (
              <Card title="Compliance overview" actions={<Badge>Rulebook v{comp.rulebook_version}</Badge>}>
                <div className="kpi-row small">
                  <Kpi label="Reports" value={comp.reports} />
                  <Kpi label="Approved" value={comp.approved} />
                  <Kpi label="Blocked" value={comp.blocked} tone={comp.blocked ? "red" : ""} />
                  <Kpi label="Avg score" value={comp.avg_score == null ? "—" : `${comp.avg_score}%`} />
                </div>
                <h4>Blocking failures by rule</h4>
                {comp.blocking_by_rule.length ? (
                  <HBars data={comp.blocking_by_rule.map((r) => ({ label: `${r.rule_id} ${r.name}`, value: r.reports, tone: "red" }))} />
                ) : <p className="muted small-text">No blocking failures in open reports.</p>}
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}
