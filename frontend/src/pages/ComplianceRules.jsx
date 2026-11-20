import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, ErrorBox, Loading, Modal, fmtDate } from "../components/ui.jsx";

const SEVERITIES = ["minor", "major", "critical"];

export default function ComplianceRules({ can, notify }) {
  const [data, setData] = useState(null);
  const [edit, setEdit] = useState(null); // { rule, isNew }
  const [history, setHistory] = useState(null);
  const [impact, setImpact] = useState(null);
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const canEdit = can("compliance:edit");

  const load = () => api.rules().then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const toggle = async (r, field) => {
    try {
      const res = await api.updateRule(r.rule_id, { [field]: !r[field] }, `${field} toggled`);
      setImpact(res.impact); notify(`${r.rule_id} updated (rulebook v${res.rulebook_version})`, "green"); load();
    } catch (e) { notify(e.message, "red"); }
  };

  const exportJson = async () => {
    try {
      const rules = await api.exportRules();
      const url = URL.createObjectURL(new Blob([JSON.stringify(rules, null, 2)], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `rulebook_v${data.rulebook_version}.json` });
      a.click(); URL.revokeObjectURL(url);
    } catch (e) { notify(e.message, "red"); }
  };

  const importJson = async (file) => {
    if (!file) return;
    try {
      const rules = JSON.parse(await file.text());
      const res = await api.importRules(Array.isArray(rules) ? rules : rules.rules);
      notify(`Imported: ${res.created.length} new, ${res.updated.length} updated`, "green");
      setImpact(res.impact); load();
    } catch (e) { notify(`Import failed: ${e.message}`, "red"); }
    finally { fileRef.current.value = ""; }
  };

  const showHistory = async (r) => {
    try { setHistory({ rule: r, versions: await api.ruleHistory(r.rule_id) }); } catch (e) { notify(e.message, "red"); }
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Compliance Rules</h1>
          <p className="muted">Editable, versioned rulebook. Every report is checked against the active version; every change is audit-logged.</p>
        </div>
        <div className="row wrap">
          {data && <Badge tone="indigo">Rulebook v{data.rulebook_version}</Badge>}
          <button className="ghost" onClick={exportJson}>Export JSON</button>
          {canEdit && <>
            <input ref={fileRef} type="file" accept=".json" hidden onChange={(e) => importJson(e.target.files?.[0])} />
            <button className="ghost" onClick={() => fileRef.current.click()}>Import JSON</button>
            <button className="primary" onClick={() => setEdit({ isNew: true, rule: {
              rule_id: `R-${String((data?.rules.length || 0) + 1).padStart(3, "0")}`, name: "", type: "threshold",
              clause_ref: "Synthetic", description: "", params: { metric: "defect_rate_pct", max: 5 },
              severity: "minor", blocking: false, active: true } })}>+ New rule</button>
          </>}
        </div>
      </header>
      <div className="banner">⚠️ Synthetic rulebook for the hackathon. Clause references are placeholders modelled on
        IATF 16949 / ISO 9001-style requirements – verify against your organisation's actual standards.</div>
      <ErrorBox error={error} />

      {impact && impact.length > 0 && (
        <Card title="Impact of last change on open reports" actions={<button className="ghost small" onClick={() => setImpact(null)}>Dismiss</button>}>
          <ul className="impact">{impact.map((i) => (
            <li key={i.report_id}><strong>{i.report_id}</strong> ({i.lot}): score {i.score_before}% → <b>{i.score_after}%</b>
              {JSON.stringify(i.blocking_before) !== JSON.stringify(i.blocking_after) &&
                <> · blocking: {i.blocking_before.join(", ") || "none"} → <b className="text-red">{i.blocking_after.join(", ") || "none"}</b></>}
            </li>))}</ul>
        </Card>
      )}
      {impact && impact.length === 0 && <div className="banner ok">Change saved – no open report changed outcome.</div>}

      {!data ? <Loading /> : (
        <Card>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Rule</th><th>Type</th><th>Parameters</th><th>Severity</th><th>Blocking</th><th>Active</th><th>Version</th><th></th></tr></thead>
              <tbody>
                {data.rules.map((r) => (
                  <tr key={r.rule_id} className={r.active ? "" : "row-muted"}>
                    <td><strong>{r.rule_id} · {r.name}</strong><div className="muted small-text">{r.description}</div>
                      <div className="muted small-text">📖 {r.clause_ref}</div></td>
                    <td><code>{r.type}</code></td>
                    <td><code className="params">{JSON.stringify(r.params)}</code></td>
                    <td><Badge tone={r.severity === "critical" ? "red" : r.severity === "major" ? "amber" : "neutral"}>{r.severity}</Badge></td>
                    <td>{canEdit ? <input type="checkbox" checked={!!r.blocking} onChange={() => toggle(r, "blocking")} /> : r.blocking ? "Yes" : "No"}</td>
                    <td>{canEdit ? <input type="checkbox" checked={!!r.active} onChange={() => toggle(r, "active")} /> : r.active ? "Yes" : "No"}</td>
                    <td className="small-text">v{r.version}<div className="muted">{r.changed_by} · {fmtDate(r.changed_at)}</div></td>
                    <td className="nowrap">
                      {canEdit && <button className="ghost small" onClick={() => setEdit({ rule: { ...r }, isNew: false })}>Edit</button>}{" "}
                      <button className="ghost small" onClick={() => showHistory(r)}>History</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {edit && <RuleForm edit={edit} types={data?.rule_types || []} onClose={() => setEdit(null)}
                         onSaved={(res) => { setEdit(null); setImpact(res.impact); notify(`Saved – rulebook v${res.rulebook_version}`, "green"); load(); }} />}

      {history && (
        <Modal title={`History – ${history.rule.rule_id} ${history.rule.name}`} onClose={() => setHistory(null)} wide>
          <ul className="timeline">
            {history.versions.map((v) => (
              <li key={v.version}><strong>v{v.version}</strong> (rulebook v{v.rulebook_version}) · {v.change_note}
                <div className="muted small-text">{v.changed_by} · {fmtDate(v.changed_at)}</div>
                <code className="params">{JSON.stringify(v.rule.params)} · {v.rule.severity} · blocking {String(v.rule.blocking)} · active {String(v.rule.active)}</code>
              </li>
            ))}
          </ul>
        </Modal>
      )}
    </div>
  );
}

function RuleForm({ edit, types, onClose, onSaved }) {
  const [rule, setRule] = useState(edit.rule);
  const [params, setParams] = useState(JSON.stringify(edit.rule.params, null, 2));
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setRule((r) => ({ ...r, [k]: v }));

  const save = async () => {
    setError("");
    let parsed;
    try { parsed = JSON.parse(params); } catch { setError("Parameters must be valid JSON, e.g. {\"hours\": 12}"); return; }
    setBusy(true);
    try {
      if (edit.isNew) {
        onSaved(await api.createRule({ ...rule, params: parsed }, note || "Created in UI"));
      } else {
        const changes = {};
        for (const key of ["name", "clause_ref", "description", "severity", "blocking", "active"]) {
          if (rule[key] !== edit.rule[key]) changes[key] = rule[key];
        }
        if (JSON.stringify(parsed) !== JSON.stringify(edit.rule.params)) changes.params = parsed;
        if (!Object.keys(changes).length) { onClose(); return; }
        onSaved(await api.updateRule(rule.rule_id, changes, note || "Edited in UI"));
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal title={edit.isNew ? "New compliance rule" : `Edit ${rule.rule_id}`} onClose={onClose} wide>
      <div className="form grid-2">
        <label>Rule ID<input value={rule.rule_id} disabled={!edit.isNew} onChange={(e) => set("rule_id", e.target.value)} /></label>
        <label>Name<input value={rule.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>Type {edit.isNew ? (
          <select value={rule.type} onChange={(e) => set("type", e.target.value)}>{types.map((t) => <option key={t}>{t}</option>)}</select>
        ) : <input value={rule.type} disabled />}</label>
        <label>Severity<select value={rule.severity} onChange={(e) => set("severity", e.target.value)}>{SEVERITIES.map((s) => <option key={s}>{s}</option>)}</select></label>
        <label className="span-2">Clause reference<input value={rule.clause_ref} onChange={(e) => set("clause_ref", e.target.value)} /></label>
        <label className="span-2">Description<input value={rule.description} onChange={(e) => set("description", e.target.value)} /></label>
        <label className="span-2">Parameters (JSON)<textarea className="mono" rows={5} value={params} onChange={(e) => setParams(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={!!rule.blocking} onChange={(e) => set("blocking", e.target.checked)} /> Blocks approval when failed</label>
        <label className="check"><input type="checkbox" checked={!!rule.active} onChange={(e) => set("active", e.target.checked)} /> Active</label>
        <label className="span-2">Change note (saved in audit log)<input value={note} placeholder="Why is this changing?" onChange={(e) => setNote(e.target.value)} /></label>
      </div>
      {error && <div className="error">⚠️ {error}</div>}
      <div className="row end">
        <button className="ghost" onClick={onClose}>Cancel</button>
        <button className="primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save new version"}</button>
      </div>
    </Modal>
  );
}
