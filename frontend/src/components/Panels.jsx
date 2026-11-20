import { useState } from "react";
import { Badge, Card, RESULT_ICON } from "./ui.jsx";

export function GuardrailPanel({ checks = [], title = "🛡️ AI guardrails" }) {
  const [open, setOpen] = useState(null);
  const warn = checks.filter((c) => c.status !== "pass").length;
  return (
    <Card title={title} actions={<Badge tone={warn ? "amber" : "green"}>{warn ? `${warn} to review` : "All passed"}</Badge>}>
      <ul className="checklist-panel">
        {checks.map((c, i) => (
          <li key={i} className={`chk ${c.status}`} onClick={() => setOpen(open === i ? null : i)}>
            <div className="chk-row">
              <span>{RESULT_ICON[c.status]}</span>
              <div>
                <strong>{c.check}</strong>
                <div className="muted small-text">{c.detail}</div>
              </div>
            </div>
            {open === i && c.items?.length > 0 && (
              <ul className="chk-items">{c.items.map((it, j) => <li key={j}>{it}</li>)}</ul>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function CompliancePanel({ compliance }) {
  if (!compliance) return null;
  const score = compliance.score_pct;
  const tone = compliance.blocking_failures.length ? "red" : score >= 80 ? "green" : "amber";
  return (
    <Card title="⚖️ Compliance check" actions={<Badge tone="neutral">Rulebook v{compliance.rulebook_version}</Badge>}>
      <div className="score-row">
        <div className={`score-ring ${tone}`}>{Math.round(score)}%</div>
        <div className="small-text">
          <div>✅ {compliance.passed} passed · ❌ {compliance.failed} failed · ⚠️ {compliance.warnings} warnings</div>
          {compliance.blocking_failures.length ? (
            <div className="text-red">Approval blocked by {compliance.blocking_failures.join(", ")}</div>
          ) : (
            <div className="text-green">No blocking failures</div>
          )}
        </div>
      </div>
      <ul className="checklist-panel">
        {compliance.results.map((r) => (
          <li key={r.rule_id} className={`chk ${r.result}`}>
            <div className="chk-row">
              <span>{RESULT_ICON[r.result]}</span>
              <div>
                <strong>{r.rule_id} · {r.name}</strong>{" "}
                {r.blocking && <Badge tone="red">blocking</Badge>}{" "}
                {r.advisory && <Badge tone="neutral" title="AI-assisted, advisory only">advisory</Badge>}
                <div className="muted small-text">{r.reason}</div>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
