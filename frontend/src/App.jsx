import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { Toast } from "./components/ui.jsx";
import { Icon, Logo } from "./components/Icons.jsx";
import Login from "./pages/Login.jsx";
import LiveFeed from "./pages/LiveFeed.jsx";
import Reports from "./pages/Reports.jsx";
import ReportEditor from "./pages/ReportEditor.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import ComplianceRules from "./pages/ComplianceRules.jsx";
import AuditLog from "./pages/AuditLog.jsx";
import Assistant from "./pages/Assistant.jsx";
import FinOps from "./pages/FinOps.jsx";
import CostBenefit from "./pages/CostBenefit.jsx";
import QualityCost from "./pages/QualityCost.jsx";

// Menu items appear only if the user's role has the permission (same permissions the backend enforces).
const NAV = [
  { id: "live", label: "Live Inspection", icon: "live", perm: "inspection:view", component: LiveFeed },
  { id: "reports", label: "Reports", icon: "reports", perm: "report:view", component: Reports },
  { id: "dashboard", label: "Dashboard", icon: "dashboard", perm: "analytics:view", component: Dashboard },
  { id: "compliance", label: "Compliance Rules", icon: "compliance", perm: "compliance:view", component: ComplianceRules },
  { id: "audit", label: "Audit Log", icon: "audit", perm: "audit:view", component: AuditLog },
  { id: "assistant", label: "Ask Quality AI", icon: "assistant", perm: "assistant:use", component: Assistant },
  { id: "quality-cost", label: "Quality Cost", icon: "qcost", perm: "qcost:view", component: QualityCost },
  { id: "value", label: "Solution ROI", icon: "value", perm: "cba:view", component: CostBenefit },
  { id: "finops", label: "AI Cost & Ops", icon: "finops", perm: "finops:view", component: FinOps },
];

// Tiny hash router: #/reports, #/report/RPT-123
function parseHash() {
  const [, page = "", id = ""] = window.location.hash.split("/");
  return { page, id: decodeURIComponent(id) };
}

export default function App() {
  const [session, setSession] = useState(null); // { user, role_label, permissions }
  const [checking, setChecking] = useState(!!getToken());
  const [route, setRoute] = useState(parseHash());
  const [health, setHealth] = useState(null);
  const [toast, setToast] = useState(null);

  const logout = useCallback(() => { setToken(""); setSession(null); }, []);
  useEffect(() => setUnauthorizedHandler(logout), [logout]);

  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setSession).catch(() => setToken("")).finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (session) api.health().then(setHealth).catch(() => setHealth(null));
  }, [session, route.page]);

  const navigate = useCallback((page, id = "") => {
    window.location.hash = id ? `/${page}/${encodeURIComponent(id)}` : `/${page}`;
  }, []);
  const notify = useCallback((text, tone = "") => setToast({ text, tone }), []);

  if (checking) return <div className="center-screen">Loading…</div>;
  if (!session) {
    return <Login onLogin={(s) => { setToken(s.token); setSession(s); navigate("reports"); }} />;
  }

  const can = (perm) => session.permissions.includes(perm);
  const nav = NAV.filter((n) => can(n.perm));
  let Page, props = { can, navigate, notify, user: session.user };
  if (route.page === "report" && route.id) {
    Page = ReportEditor;
    props = { ...props, id: route.id };
  } else {
    Page = (nav.find((n) => n.id === route.page) || nav.find((n) => n.id === "reports") || nav[0]).component;
  }
  const active = route.page === "report" ? "reports" : route.page || "reports";

  return (
    <div className="layout">
      <aside className="sidebar no-print">
        <div className="brand">
          <span className="logo"><Logo /></span>
          <div>
            <div className="brand-name">InspectIQ</div>
            <div className="brand-sub">Quality Intelligence</div>
          </div>
        </div>
        <nav>
          <div className="nav-label">Navigation</div>
          {nav.map((n) => (
            <button key={n.id} className={`nav-item ${active === n.id ? "active" : ""}`} onClick={() => navigate(n.id)}>
              <Icon name={n.icon} /> {n.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          {/* AI model / data-source status is an operations detail - only IT Support & FinOps sees it */}
          {health && can("finops:edit") && (
            <div className="status">
              <span className={`dot ${health.llm_provider === "mock" ? "amber" : "green"}`} />
              <div className="status-text">
                <div>{health.llm_provider === "mock" ? "Template mode (no LLM key)" : `${health.llm_provider} · ${health.model}`}</div>
                {health.fallback_model && health.llm_provider !== "mock" && <small>Fallback: {health.fallback_model}</small>}
                <small>Data: {health.data_source} · Rulebook v{health.rulebook_version}</small>
              </div>
            </div>
          )}
          <div className="user-box">
            <div>
              <div className="user-name">{session.user.name}</div>
              <div className="user-role">{session.role_label}</div>
            </div>
            <button className="ghost small" onClick={logout}>Sign out</button>
          </div>
          <div className="synthetic-note">All data is synthetic</div>
        </div>
      </aside>
      <main className="content">
        <Page key={route.page + route.id} {...props} />
      </main>
      <Toast toast={toast} onDone={() => setToast(null)} />
    </div>
  );
}
