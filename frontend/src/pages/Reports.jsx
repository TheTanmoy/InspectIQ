import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Loading, StatusPill, fmtDate } from "../components/ui.jsx";

const LINES = [{ id: "L1", name: "L1 · Brake Disc" }, { id: "L2", name: "L2 · Gear Shaft" }, { id: "L3", name: "L3 · Piston Rod" }];

export default function Reports({ can, navigate, notify }) {
  const [list, setList] = useState(null);
  const [status, setStatus] = useState("");
  const [line, setLine] = useState("L1");
  const [lots, setLots] = useState([]);
  const [lot, setLot] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");

  const load = () => api.reports(status).then(setList).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.lots(line, 30).then((l) => { setLots(l); setLot((l.find((x) => !x.in_progress) || l[0])?.lot || ""); }).catch((e) => setError(e.message));
  }, [line]);

  const generate = async () => {
    setBusy(true); setError(""); setElapsed(0);
    const start = Date.now();
    const t = setInterval(() => setElapsed(((Date.now() - start) / 1000).toFixed(1)), 100);
    try {
      const rep = await api.generate(lot);
      notify(`Report ${rep.id} generated in ${rep.ai.generation_seconds}s`, "green");
      navigate("report", rep.id);
    } catch (e) { setError(e.message); }
    finally { clearInterval(t); setBusy(false); }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Inspection Reports</h1>
          <p className="muted">Generate a standardized report for any lot in seconds, then review, edit and approve.</p>
        </div>
      </header>

      {can("report:generate") && (
        <Card title="✨ Generate a new report" className="generate-card">
          <div className="row wrap align-end">
            <label className="field">Production line
              <select value={line} onChange={(e) => setLine(e.target.value)}>
                {LINES.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
            <label className="field grow">Lot / shift
              <select value={lot} onChange={(e) => setLot(e.target.value)}>
                {lots.map((l) => (
                  <option key={l.lot} value={l.lot}>
                    {l.lot} · shift {l.shift} · {l.in_progress ? "🔴 in progress" : `ended ${fmtDate(l.shift_end)}`} · {l.sampled} sampled
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" onClick={generate} disabled={busy || !lot}>
              {busy ? `Generating… ${elapsed}s` : "Generate report"}
            </button>
          </div>
          <p className="muted small-text">Pulls sensor, camera and manual-check data for the lot → computes statistics →
            AI writes the narrative → guardrails and compliance rules check it.</p>
        </Card>
      )}
      <ErrorBox error={error} />

      <Card title="All reports" actions={
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="in_review">In review</option>
          <option value="reviewed">Reviewed</option>
          <option value="awaiting_release">Awaiting release</option>
          <option value="approved">Approved</option>
        </select>
      }>
        {!list ? <Loading /> : !list.length ? <Empty>No reports yet. Generate the first one above.</Empty> : (
          <div className="table-wrap">
            <table className="table clickable">
              <thead>
                <tr><th>Report</th><th>Lot</th><th>Status</th><th>Defect rate</th><th>Compliance</th>
                  <th>Guardrails</th><th>AI</th><th>Created</th></tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id} onClick={() => navigate("report", r.id)}>
                    <td><strong>{r.id}</strong><div className="muted small-text">{r.part}</div></td>
                    <td>{r.lot}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td>{r.defect_rate_pct}% {r.critical_defects > 0 && <Badge tone="red">{r.critical_defects} critical</Badge>}</td>
                    <td>
                      <div className="bar"><span style={{ width: `${r.compliance_score}%` }}
                        className={r.blocking_failures.length ? "red" : r.compliance_score >= 80 ? "green" : "amber"} /></div>
                      <span className="small-text">{Math.round(r.compliance_score)}%
                        {r.blocking_failures.length > 0 && <span className="text-red"> · blocked</span>}</span>
                    </td>
                    <td>{r.guardrail_warnings ? <Badge tone="amber">{r.guardrail_warnings} to review</Badge> : <Badge tone="green">OK</Badge>}</td>
                    <td><Badge>{r.ai_mode}</Badge></td>
                    <td className="small-text">{fmtDate(r.created_at)}<div className="muted">{r.created_by}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
