import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CompliancePanel, GuardrailPanel } from "../components/Panels.jsx";
import { Badge, Card, ErrorBox, Kpi, Loading, Modal, StatusPill, fmtDate, sevTone } from "../components/ui.jsx";

const DISPOSITIONS = ["", "scrap", "rework", "hold", "use-as-is (deviation)"];
const SECTION_KEYS = ["purpose", "executive_summary", "defect_descriptions", "measurement_analysis", "root_causes",
  "recommended_actions", "containment_actions"];

const clone = (o) => JSON.parse(JSON.stringify(o));

export default function ReportEditor({ id, can, navigate, notify, user }) {
  const [rep, setRep] = useState(null);
  const [sections, setSections] = useState(null);
  const [dispositions, setDispositions] = useState({});
  const [verify, setVerify] = useState([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [rewrite, setRewrite] = useState(null); // {section, proposal, guardrails}
  const [rewriting, setRewriting] = useState("");
  const [image, setImage] = useState(null);
  const [history, setHistory] = useState(null);
  const [commentFor, setCommentFor] = useState(null);
  const [comment, setComment] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.report(id);
      setRep(r);
      setSections(clone(r.sections));
      setDispositions({});
      setVerify([]);
    } catch (e) { setError(e.message); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const locked = ["approved", "awaiting_release"].includes(rep?.status);
  const editable = can("report:edit") && !locked && !(rep?.status === "reviewed" && user.role === "inspector");

  const dirtySections = useMemo(() => {
    if (!rep || !sections) return {};
    return Object.fromEntries(SECTION_KEYS.filter((k) => JSON.stringify(rep.sections[k]) !== JSON.stringify(sections[k]))
      .map((k) => [k, sections[k]]));
  }, [rep, sections]);
  const dirty = Object.keys(dirtySections).length > 0 || Object.keys(dispositions).length > 0 || verify.length > 0;

  const save = async () => {
    setSaving(true); setError("");
    try {
      const patch = { note: "Edited in report editor" };
      if (Object.keys(dirtySections).length) patch.sections = dirtySections;
      if (Object.keys(dispositions).length) patch.dispositions = dispositions;
      if (verify.length) patch.verify = verify;
      const r = await api.updateReport(id, patch);
      setRep(r); setSections(clone(r.sections)); setDispositions({}); setVerify([]);
      notify("Changes saved and recorded in the audit log", "green");
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  const doAction = async (action, text = "") => {
    if (dirty) { notify("Save your changes first", "amber"); return; }
    setError("");
    try {
      const r = await api.action(id, action, text);
      setRep(r); setSections(clone(r.sections));
      notify(`Done: ${action.replace("_", " ")}`, "green");
    } catch (e) { setError(e.message); }
  };

  const askRewrite = async (section) => {
    setRewriting(section);
    try { setRewrite(await api.rewrite(id, section, "Make it clearer and more concise for a quality manager.")); }
    catch (e) { setError(e.message); }
    finally { setRewriting(""); }
  };

  const openHistory = async () => {
    try {
      const [versions, trail] = await Promise.all([api.versions(id), api.reportAudit(id)]);
      setHistory({ versions, trail });
    } catch (e) { setError(e.message); }
  };

  if (error && !rep) return <div className="page"><ErrorBox error={error} /></div>;
  if (!rep || !sections) return <div className="page"><Loading text="Loading report…" /></div>;

  const m = rep.meta, k = rep.kpis, s = rep.signoffs, c = rep.compliance;
  const set = (key, value) => setSections((x) => ({ ...x, [key]: value }));
  const hasCritical = rep.defects.some((d) => d.severity === "critical");
  const approveBlocked = c && !c.can_approve;
  // segregation of duties: each sign-off by a different person (enforced by the API too)
  const ownSubmission = user.username === s.submitted_by;
  const signedAlready = [s.submitted_by, s.reviewed_by].includes(user.username);
  const signedAny = [s.submitted_by, s.reviewed_by, s.approved_by].includes(user.username);
  const releaseStep = (rep.approval_chain || []).find((st) => st.key === "release");
  const STATE_TONE = { done: "green", current: "amber", pending: "neutral" };
  const STATE_LABEL = { done: "signed", current: "awaiting", pending: "not started" };

  return (
    <div className="page report-page">
      <div className="no-print">
        <button className="link" onClick={() => navigate("reports")}>← All reports</button>
      </div>
      <header className="page-header">
        <div>
          <h1>{rep.id} <StatusPill status={rep.status} /></h1>
          <p className="muted">{m.part} · {m.line_name} ({m.line}) · Lot <strong>{m.lot}</strong> · Shift {m.shift} ·
            {" "}{fmtDate(m.shift_start)} – {fmtDate(m.shift_end)}</p>
          <div className="row wrap">
            <Badge tone={rep.ai.mode === "llm" ? "indigo" : "neutral"}>
              {/* the model name is an operations detail - only IT Support & FinOps sees it */}
              {rep.ai.mode === "llm" ? (can("finops:edit") ? `AI: ${rep.ai.model}` : "AI-assisted")
                : rep.ai.mode === "fallback" ? "AI unavailable – template used" : "Template mode"}
            </Badge>
            <Badge tone="green">⏱ Generated in {rep.ai.generation_seconds}s · manual ≈ {rep.ai.manual_baseline_minutes} min (assumed)</Badge>
            <Badge tone={locked ? "green" : "amber"}>{rep.ai.label}</Badge>
            {rep.edited_by_human && <Badge>✍️ Edited by staff</Badge>}
          </div>
        </div>
        <div className="row wrap no-print actions">
          {editable && <button className="primary" onClick={save} disabled={!dirty || saving}>{saving ? "Saving…" : dirty ? "Save changes" : "Saved"}</button>}
          {hasCritical && !s.escalated_at && can("report:edit") && !locked &&
            <button className="danger" onClick={() => doAction("escalate")}>🚨 Escalate critical defect</button>}
          {rep.status === "draft" && can("report:submit") && <button className="ghost" onClick={() => doAction("submit")}>Submit for review</button>}
          {rep.status === "in_review" && can("report:review") &&
            <button className="ghost" onClick={() => doAction("review")} disabled={ownSubmission}
                    title={ownSubmission ? "You submitted this report - a different supervisor must review it" : "Mark reviewed"}>Mark reviewed</button>}
          {["in_review", "reviewed"].includes(rep.status) && can("report:review") &&
            <button className="ghost" onClick={() => { setCommentFor("request_changes"); setComment(""); }}>Request changes</button>}
          {rep.status === "reviewed" && can("report:approve") && (
            <button className="primary" onClick={() => doAction("approve")} disabled={approveBlocked || signedAlready}
                    title={approveBlocked ? `Blocked by ${c.blocking_failures.join(", ")}`
                      : signedAlready ? "You already signed this report - a different quality manager must approve it" : "Approve report"}>
              {approveBlocked ? "Approval blocked" : signedAlready ? "Needs another approver" : "Approve & release"}
            </button>
          )}
          {rep.status === "awaiting_release" && can("report:release") && (
            <>
              <button className="ghost" onClick={() => { setCommentFor("send_back"); setComment(""); }}>Send back</button>
              <button className="primary" onClick={() => doAction("release")} disabled={signedAny || approveBlocked}
                      title={signedAny ? "You already signed this report - a different Plant Quality Head must release it"
                        : approveBlocked ? `Blocked by ${c.blocking_failures.join(", ")}` : "Release high-risk report"}>
                {signedAny ? "Needs another signer" : "Release lot"}
              </button>
            </>
          )}
          <button className="ghost" onClick={openHistory}>History</button>
          <button className="ghost" onClick={() => window.print()}>Export PDF</button>
        </div>
      </header>
      <ErrorBox error={error} />
      {releaseStep && rep.status !== "approved" && (
        <div className="banner high-risk">
          <strong>High-risk report.</strong> {releaseStep.duty.replace("Second, independent sign-off required because this report is high-risk. ", "")}
          {" "}After Quality Manager approval it also needs release by the <strong>Plant Quality Head</strong>.
        </div>
      )}

      <div className="report-grid">
        <div className="report-doc">
          <div className="print-only print-header">
            <h2>Quality Inspection Report {rep.id}</h2>
            <div>Template {m.template} · Generated by InspectIQ · Status: {rep.status} · {rep.ai.label}</div>
          </div>

          <div className="kpi-row">
            <Kpi label="Parts inspected" value={k.parts_inspected} sub={`of lot size ${m.lot_size}`} />
            <Kpi label="Defective parts" value={k.defective_parts} tone={k.defective_parts ? "amber" : ""} />
            <Kpi label="Defect rate" value={`${k.defect_rate_pct}%`} tone={k.defect_rate_pct > 5 ? "red" : ""} />
            <Kpi label="First-pass yield" value={`${k.first_pass_yield_pct}%`} />
            <Kpi label="Critical" value={k.critical_defects} tone={k.critical_defects ? "red" : ""} />
          </div>

          <Card title="Purpose & scope" className="purpose-card">
            <TextArea value={sections.purpose || ""} onChange={(v) => set("purpose", v)} disabled={!editable} rows={6} />
          </Card>

          <Card title="1. Executive summary" actions={editable && rewriteBtn("executive_summary")}>
            <TextArea value={sections.executive_summary} onChange={(v) => set("executive_summary", v)} disabled={!editable} rows={5} />
          </Card>

          <Card title="2. Defect descriptions (AI-generated, standardized codes)">
            <ListEditor items={sections.defect_descriptions} disabled={!editable} onChange={(v) => set("defect_descriptions", v)}
              blank={{ defect_code: "UNCLASSIFIED", title: "", description: "", severity: "minor", evidence: [] }}
              render={(it, upd) => (
                <>
                  <div className="row wrap">
                    <Badge tone={sevTone(it.severity)}>{it.defect_code}</Badge>
                    <input className="grow" value={it.title} placeholder="Title" disabled={!editable} onChange={(e) => upd({ title: e.target.value })} />
                    <select value={it.severity} disabled={!editable} onChange={(e) => upd({ severity: e.target.value })}>
                      <option>minor</option><option>major</option><option>critical</option>
                    </select>
                  </div>
                  <TextArea value={it.description} disabled={!editable} onChange={(v) => upd({ description: v })} rows={2} />
                  {it.evidence?.length > 0 && <div className="muted small-text">Evidence: {it.evidence.join(", ")}</div>}
                </>
              )} />
          </Card>

          <Card title={`3. Camera detections (${rep.defects.length})`}>
            {!rep.defects.length ? <p className="muted">No camera detections in this lot.</p> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>ID</th><th>Part serial</th><th>Code</th><th>Severity</th><th>Confidence</th><th>Location</th><th>Image</th><th>Verified</th></tr></thead>
                  <tbody>
                    {rep.defects.map((d) => {
                      const pending = verify.includes(d.id);
                      return (
                        <tr key={d.id} className={d.needs_verification && !d.verified ? "row-warn" : ""}>
                          <td>{d.id}</td><td><code>{d.part_serial}</code></td>
                          <td title={`camera label: ${d.camera_label}`}>{d.defect_code} <span className="muted small-text">{d.defect_name}</span></td>
                          <td><Badge tone={sevTone(d.severity)}>{d.severity}</Badge></td>
                          <td className={d.needs_verification ? "text-amber" : ""}>{Math.round(d.confidence * 100)}%</td>
                          <td>{d.location}</td>
                          <td>{d.image_id ? <button className="link" onClick={() => setImage(d)}>📷 view</button> : "—"}</td>
                          <td>
                            {d.verified ? <span title={`by ${d.verified_by}`}>✅ {d.verified_by}</span>
                              : d.needs_verification ? (
                                <label className="check">
                                  <input type="checkbox" disabled={!editable} checked={pending}
                                         onChange={(e) => setVerify((v) => e.target.checked ? [...v, d.id] : v.filter((x) => x !== d.id))} />
                                  confirm
                                </label>
                              ) : <span className="muted">not needed</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="4. Measurement analysis" actions={editable && rewriteBtn("measurement_analysis")}>
            <TextArea value={sections.measurement_analysis} onChange={(v) => set("measurement_analysis", v)} disabled={!editable} rows={3} />
            <div className="table-wrap">
              <table className="table compact">
                <thead><tr><th>Feature</th><th>Station</th><th>n</th><th>Mean</th><th>Std</th><th>LSL</th><th>USL</th><th>Cpk</th><th>Out of spec</th><th>Gauge</th></tr></thead>
                <tbody>
                  {rep.features.map((f) => (
                    <tr key={f.feature}>
                      <td>{f.feature} <span className="muted small-text">{f.unit}</span></td><td>{f.station}</td><td>{f.n}</td>
                      <td>{f.mean}</td><td>{f.std}</td><td>{f.lsl}</td><td>{f.usl}</td>
                      <td><Badge tone={f.cpk == null ? "neutral" : f.cpk < 1 ? "red" : f.cpk < 1.33 ? "amber" : "green"}>{f.cpk ?? "—"}</Badge></td>
                      <td>{f.out_of_spec || "—"}</td><td>{f.gauge_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {rep.out_of_spec.length > 0 && (
            <Card title={`5. Nonconforming measurements – disposition (${rep.out_of_spec.length})`}>
              <p className="muted small-text">The AI never decides accept/reject. Choose a disposition for each item (suggested: hold).</p>
              <table className="table compact">
                <thead><tr><th>Part serial</th><th>Feature</th><th>Value</th><th>Limits</th><th>Disposition</th></tr></thead>
                <tbody>
                  {rep.out_of_spec.map((o, i) => (
                    <tr key={i}>
                      <td><code>{o.part_serial}</code></td><td>{o.feature}</td>
                      <td className="text-red">{o.value} {o.unit}</td><td>{o.lsl} – {o.usl}</td>
                      <td>
                        <select disabled={!editable} value={dispositions[i] ?? o.disposition}
                                onChange={(e) => setDispositions((d) => ({ ...d, [i]: e.target.value }))}>
                          {DISPOSITIONS.map((x) => <option key={x} value={x}>{x || `— choose (suggested: ${o.suggested_disposition}) —`}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <Card title="6. Root-cause hypotheses">
            <ListEditor items={sections.root_causes} disabled={!editable} onChange={(v) => set("root_causes", v)}
              blank={{ hypothesis: "", evidence: "", confidence: "low" }}
              render={(it, upd) => (
                <>
                  <div className="row">
                    <input className="grow" value={it.hypothesis} placeholder="Specific, evidence-based cause" disabled={!editable}
                           onChange={(e) => upd({ hypothesis: e.target.value })} />
                    <select value={it.confidence} disabled={!editable} onChange={(e) => upd({ confidence: e.target.value })}>
                      <option>low</option><option>medium</option><option>high</option>
                    </select>
                  </div>
                  <TextArea value={it.evidence} rows={2} disabled={!editable} onChange={(v) => upd({ evidence: v })} placeholder="Evidence" />
                </>
              )} />
          </Card>

          <Card title="7. Recommended actions">
            <ListEditor items={sections.recommended_actions} disabled={!editable} onChange={(v) => set("recommended_actions", v)}
              blank={{ action: "", owner_role: "Quality Manager", priority: "medium" }}
              render={(it, upd) => (
                <div className="row wrap">
                  <input className="grow" value={it.action} placeholder="Action" disabled={!editable} onChange={(e) => upd({ action: e.target.value })} />
                  <select value={it.owner_role} disabled={!editable} onChange={(e) => upd({ owner_role: e.target.value })}>
                    {["Inspector", "Line Supervisor", "Quality Manager", "Maintenance"].map((o) => <option key={o}>{o}</option>)}
                  </select>
                  <select value={it.priority} disabled={!editable} onChange={(e) => upd({ priority: e.target.value })}>
                    <option>high</option><option>medium</option><option>low</option>
                  </select>
                </div>
              )} />
          </Card>

          <Card title="8. Containment actions">
            <ListEditor items={sections.containment_actions} disabled={!editable} onChange={(v) => set("containment_actions", v)} blank=""
              render={(it, upd) => <input className="grow full" value={it} disabled={!editable} onChange={(e) => upd(e.target.value)} />} />
          </Card>

          <Card title="9. Inspector notes (filtered)">
            {!rep.manual_findings.length ? <p className="muted">No notes recorded.</p> : (
              <table className="table compact">
                <thead><tr><th>Check</th><th>Result</th><th>Note (as sent to AI)</th><th>Standard code</th></tr></thead>
                <tbody>
                  {rep.manual_findings.map((f, i) => (
                    <tr key={i}>
                      <td>{f.item}</td><td><Badge tone={f.result === "fail" ? "red" : "green"}>{f.result}</Badge></td>
                      <td>{f.note} {f.original_note_hidden && <Badge tone="amber" title="Personal data masked or instructions removed">🛡️ filtered</Badge>}</td>
                      <td>{f.standard_code || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="10. Responsibilities & approval" actions={<Badge>Each step signed by a different person</Badge>}>
            <div className="table-wrap">
              <table className="table approval-table">
                <thead><tr><th>#</th><th>Step</th><th>Responsible</th><th>Duty</th><th>Signed by</th><th>Status</th></tr></thead>
                <tbody>
                  {(rep.approval_chain || []).map((st, i) => (
                    <tr key={st.key} className={`step-${st.state}`}>
                      <td><span className="step-no">{i + 1}</span></td>
                      <td><strong>{st.step}</strong></td>
                      <td className="nowrap">{st.role}</td>
                      <td className="muted small-text">{st.duty}</td>
                      <td>{st.signed_by ? <><strong>{st.signed_by}</strong><div className="muted small-text">{fmtDate(st.signed_at)}</div></> : "—"}</td>
                      <td><Badge tone={STATE_TONE[st.state]}>{STATE_LABEL[st.state]}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small-text">Prepared by <strong>{m.created_by}</strong> on {fmtDate(m.created_at)}.
              Compliance Officers maintain the rulebook and audit trail but do not sign reports.
              {approveBlocked && " Approval is currently blocked by: " + c.blocking_failures.join(", ") + "."}</p>
            {s.comments?.length > 0 && (
              <ul className="comments">
                {s.comments.map((cm, i) => <li key={i}><strong>{cm.by}</strong> ({cm.action}, {fmtDate(cm.at)}): {cm.text}</li>)}
              </ul>
            )}
          </Card>
        </div>

        <div className="report-side">
          <CompliancePanel compliance={c} />
          <GuardrailPanel checks={rep.guardrails} />
          {rep.material && (
            <Card title="Raw material" actions={rep.material.deviations?.length
              ? <Badge tone="red">off-spec</Badge> : <Badge tone="green">certificate ok</Badge>}>
              <div className="material-head">
                <div><span>Material lot</span><strong className="mono">{rep.material.material_lot}</strong></div>
                <div><span>Heat</span><strong className="mono">{rep.material.heat_number}</strong></div>
                <div><span>Supplier</span><strong>{rep.material.supplier}</strong></div>
                <div><span>Incoming</span><strong>{rep.material.incoming_result}{rep.material.deviation_ref ? ` · ${rep.material.deviation_ref}` : ""}</strong></div>
                <div style={{ gridColumn: "span 2" }}><span>Grade</span><strong>{rep.material.material}</strong></div>
              </div>
              <table className="table compact">
                <thead><tr><th>Certificate</th><th>Value</th><th>Spec</th></tr></thead>
                <tbody>
                  {rep.material.certificate.map((c) => {
                    const pos = Math.max(0, Math.min(100, (100 * c.value) / (c.max * 1.4 || 1)));
                    return (
                      <tr key={c.property} className={c.in_spec ? "" : "row-danger"}>
                        <td>{c.property}</td>
                        <td className={c.in_spec ? "" : "text-red"}><strong>{c.value}</strong>
                          <div className={`cert-range ${c.in_spec ? "" : "out"}`}><i style={{ left: `${pos}%` }} /></div></td>
                        <td className="muted nowrap">{c.min}–{c.max}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          )}
          {rep.insights?.length > 0 && (
            <Card title="Line patterns">
              {rep.insights.map((i) => (
                <div key={i.id} className="insight mini">
                  <Badge tone={i.severity === "high" ? "red" : "amber"}>{i.severity}</Badge> <strong>{i.title}</strong>
                  <div className="muted small-text">{i.detail}</div>
                </div>
              ))}
            </Card>
          )}
        </div>
      </div>

      {rewrite && (
        <Modal title={`AI rewrite proposal – ${rewrite.section.replace("_", " ")}`} onClose={() => setRewrite(null)} wide>
          <div className="grid-2">
            <div><h4>Current</h4><div className="quote">{sections[rewrite.section]}</div></div>
            <div><h4>Proposed ({rewrite.mode})</h4><div className="quote new">{rewrite.proposal}</div></div>
          </div>
          <div className="row wrap">{rewrite.guardrails.map((g, i) => <Badge key={i} tone={g.status === "pass" ? "green" : "amber"}>{g.check}: {g.detail}</Badge>)}</div>
          <div className="row end">
            <button className="ghost" onClick={() => setRewrite(null)}>Reject</button>
            <button className="primary" onClick={() => { set(rewrite.section, rewrite.proposal); setRewrite(null); }}>Accept (then Save)</button>
          </div>
        </Modal>
      )}

      {image && (
        <Modal title={`${image.part_serial} · ${image.defect_name} (${Math.round(image.confidence * 100)}%)`} onClose={() => setImage(null)}>
          <img className="defect-img" src={api.imageUrl(image.image_id)} alt={`${image.defect_name} on ${image.part_serial}`} />
          <p className="muted small-text">Camera {image.camera_id} · {image.location} · {fmtDate(image.ts)} · synthetic image</p>
        </Modal>
      )}

      {history && (
        <Modal title="Version history & audit trail" onClose={() => setHistory(null)} wide>
          <div className="grid-2">
            <div>
              <h4>Versions</h4>
              <ul className="timeline">{history.versions.map((v) => (
                <li key={v.version}><strong>v{v.version}</strong> · {v.change_note}<div className="muted small-text">{v.changed_by} · {fmtDate(v.changed_at)}</div></li>
              ))}</ul>
            </div>
            <div>
              <h4>Audit trail</h4>
              <ul className="timeline">{history.trail.map((a) => (
                <li key={a.id}><strong>{a.action}</strong> · {a.username} ({a.role})
                  <div className="muted small-text">{fmtDate(a.ts)}</div>
                  {a.after && <pre className="diff">{Object.entries(a.after).map(([key, val]) =>
                    `${key}: ${JSON.stringify(a.before?.[key] ?? null).slice(0, 80)} → ${JSON.stringify(val).slice(0, 80)}`).join("\n")}</pre>}
                </li>
              ))}</ul>
            </div>
          </div>
        </Modal>
      )}

      {commentFor && (
        <Modal title={commentFor === "send_back" ? "Send back – not released" : "Request changes"} onClose={() => setCommentFor(null)}>
          <TextArea value={comment} onChange={setComment} rows={4} placeholder="What needs to change?" />
          <div className="row end">
            <button className="ghost" onClick={() => setCommentFor(null)}>Cancel</button>
            <button className="primary" disabled={!comment.trim()} onClick={() => { doAction(commentFor, comment); setCommentFor(null); }}>Send back to draft</button>
          </div>
        </Modal>
      )}
    </div>
  );

  function rewriteBtn(section) {
    return (
      <button className="ghost small no-print" onClick={() => askRewrite(section)} disabled={!!rewriting}>
        {rewriting === section ? "Thinking…" : "✨ AI rewrite"}
      </button>
    );
  }
}

function TextArea({ value, onChange, disabled, rows = 3, placeholder }) {
  return <textarea value={value || ""} rows={rows} disabled={disabled} placeholder={placeholder}
                   onChange={(e) => onChange(e.target.value)} />;
}

function ListEditor({ items = [], onChange, render, blank, disabled }) {
  const upd = (i) => (patch) => onChange(items.map((it, j) => (j === i ? (typeof it === "string" ? patch : { ...it, ...patch }) : it)));
  return (
    <div className="list-editor">
      {!items.length && <p className="muted small-text">None recorded.</p>}
      {items.map((it, i) => (
        <div key={i} className="list-item">
          <div className="grow">{render(it, upd(i))}</div>
          {!disabled && <button className="ghost small" title="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      {!disabled && <button className="link no-print" onClick={() => onChange([...items, clone(blank)])}>+ Add</button>}
    </div>
  );
}
