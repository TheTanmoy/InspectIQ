import { useEffect } from "react";

export const fmtDate = (s) => {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d) ? s : d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const STATUS_LABEL = { draft: "Draft", in_review: "In review", reviewed: "Reviewed",
  awaiting_release: "Awaiting release", approved: "Approved" };

export function StatusPill({ status }) {
  return <span className={`pill status-${status}`}>{STATUS_LABEL[status] || status}</span>;
}

export function Badge({ tone = "neutral", children, title }) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

export const RESULT_ICON = { pass: "✅", warn: "⚠️", fail: "❌", na: "➖" };
export const sevTone = (s) => (s === "critical" ? "red" : s === "major" ? "amber" : "neutral");

export function Kpi({ label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h3>{title}</h3>}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading({ text = "Loading…" }) {
  return <div className="loading"><span className="spinner" /> {text}</div>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="error">⚠️ {error}</div>;
}

export function Empty({ children }) {
  return <div className="empty-box">{children}</div>;
}

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h3>{title}</h3>
          <button className="ghost small" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Toast({ toast, onDone }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDone, 4000);
    return () => clearTimeout(t);
  }, [toast, onDone]);
  if (!toast) return null;
  return <div className={`toast ${toast.tone || ""}`}>{toast.text}</div>;
}
