import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, fmtDate } from "../components/ui.jsx";

export default function AuditLog() {
  const [tab, setTab] = useState("actions");
  const [rows, setRows] = useState(null);
  const [llm, setLlm] = useState(null);
  const [filters, setFilters] = useState({ entity: "", username: "", action: "" });
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows(null);
    api.audit({ ...filters, limit: 300 }).then(setRows).catch((e) => setError(e.message));
  }, [filters]);
  useEffect(() => { if (tab === "llm") api.llmCalls().then(setLlm).catch((e) => setError(e.message)); }, [tab]);

  const setF = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Audit Log</h1>
          <p className="muted">Every login, report edit, workflow step, rule change and AI call – who, what, when, before and after.</p>
        </div>
        <div className="tabs">
          <button className={tab === "actions" ? "active" : ""} onClick={() => setTab("actions")}>User actions</button>
          <button className={tab === "llm" ? "active" : ""} onClick={() => setTab("llm")}>AI calls</button>
        </div>
      </header>
      <ErrorBox error={error} />

      {tab === "actions" && (
        <Card actions={
          <div className="row wrap">
            <select value={filters.entity} onChange={setF("entity")}>
              <option value="">All entities</option><option value="report">Reports</option><option value="rule">Rules</option>
              <option value="user">Logins</option><option value="assistant">Assistant</option>
            </select>
            <input placeholder="User" value={filters.username} onChange={setF("username")} />
            <input placeholder="Action contains…" value={filters.action} onChange={setF("action")} />
          </div>}>
          {!rows ? <Loading /> : (
            <div className="table-wrap">
              <table className="table compact">
                <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} className="clickable-row">
                      <td className="nowrap small-text">{fmtDate(r.ts)}</td>
                      <td>{r.username}<div className="muted small-text">{r.role}</div></td>
                      <td><Badge tone={r.action.includes("blocked") || r.action.includes("failed") ? "red" : "neutral"}>{r.action}</Badge></td>
                      <td>{r.entity} <code>{r.entity_id}</code></td>
                      <td className="small-text">
                        {open === r.id ? (
                          <pre className="diff">{JSON.stringify({ before: r.before, after: r.after, meta: r.meta }, null, 2)}</pre>
                        ) : (r.after || r.meta) ? <span className="muted">click to expand</span> : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === "llm" && (
        <Card title="AI call log (prompt version, latency, guardrail results)">
          {!llm ? <Loading /> : !llm.length ? <p className="muted">No AI calls yet (template mode does not call the LLM).</p> : (
            <table className="table compact">
              <thead><tr><th>Time</th><th>User</th><th>Purpose</th><th>Model</th><th>Prompt</th><th>Latency</th><th>OK</th><th>Guardrails / error</th></tr></thead>
              <tbody>
                {llm.map((c) => (
                  <tr key={c.id}>
                    <td className="nowrap small-text">{fmtDate(c.ts)}</td><td>{c.username}</td><td>{c.purpose}</td>
                    <td>{c.provider} · {c.model}</td><td>{c.prompt_version}</td><td>{c.latency_ms} ms</td>
                    <td>{c.ok ? "✅" : "❌"}</td>
                    <td className="small-text"><code>{c.error || JSON.stringify(c.guardrails)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}
