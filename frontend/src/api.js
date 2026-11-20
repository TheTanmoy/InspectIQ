// All backend calls live here. Components never call fetch directly.

const TOKEN_KEY = "inspectiq_token";
let token = "";
try { token = localStorage.getItem(TOKEN_KEY) || ""; } catch { /* storage blocked */ }

export const getToken = () => token;
export function setToken(t) {
  token = t || "";
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(method, path, body, { raw = false } = {}) {
  const headers = { ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running on port 8000?");
  }
  if (res.status === 401 && !path.endsWith("/login")) onUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return raw ? res : res.json();
}

const qs = (params) => {
  const p = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // auth
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  me: () => request("GET", "/api/auth/me"),
  demoUsers: () => request("GET", "/api/auth/demo-users"),
  health: () => request("GET", "/api/health"),

  // inspection data
  plant: () => request("GET", "/api/inspection/plant"),
  lots: (line, limit = 40) => request("GET", `/api/inspection/lots${qs({ line, limit })}`),
  live: (since) => request("GET", `/api/inspection/live${qs({ since })}`),
  simulator: (action) => request("POST", `/api/inspection/simulator/${action}`),
  imageUrl: (id) => `/api/inspection/images/${id}?token=${encodeURIComponent(token)}`,

  // reports
  reports: (status = "", line = "") => request("GET", `/api/reports${qs({ status, line })}`),
  generate: (lot) => request("POST", "/api/reports/generate", { lot }),
  report: (id) => request("GET", `/api/reports/${id}`),
  updateReport: (id, patch) => request("PATCH", `/api/reports/${id}`, patch),
  action: (id, action, comment = "") => request("POST", `/api/reports/${id}/actions/${action}`, { comment }),
  rewrite: (id, section, instruction) => request("POST", `/api/reports/${id}/rewrite`, { section, instruction }),
  versions: (id) => request("GET", `/api/reports/${id}/versions`),
  reportAudit: (id) => request("GET", `/api/reports/${id}/audit`),

  // analytics
  overview: (days = 30, line = "") => request("GET", `/api/analytics/overview${qs({ days, line })}`),
  spc: (line, feature, days = 60) => request("GET", `/api/analytics/spc${qs({ line, feature, days })}`),
  explainInsights: () => request("POST", "/api/analytics/insights/explain"),

  // compliance
  rules: () => request("GET", "/api/compliance/rules"),
  ruleHistory: (id) => request("GET", `/api/compliance/rules/${id}/history`),
  updateRule: (id, changes, note) => request("PUT", `/api/compliance/rules/${id}`, { changes, note }),
  createRule: (rule, note) => request("POST", "/api/compliance/rules", { rule, note }),
  exportRules: () => request("GET", "/api/compliance/export"),
  importRules: (rules) => request("POST", "/api/compliance/import", { rules }),
  complianceSummary: () => request("GET", "/api/compliance/summary"),

  // audit
  audit: (params = {}) => request("GET", `/api/audit${qs(params)}`),
  llmCalls: () => request("GET", "/api/audit/llm"),

  // finops + cost-benefit
  finopsUsage: (days = 30) => request("GET", `/api/finops/usage${qs({ days })}`),
  costBenefit: () => request("GET", "/api/finops/cost-benefit"),
  finopsSettings: (section, changes, note = "") => request("PUT", "/api/finops/settings", { section, changes, note }),
};

/** Streams the assistant reply; calls onToken(chunk) as text arrives. */
export async function streamChat({ messages, onToken, signal }) {
  const res = await fetch("/api/assistant/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ messages }),
    signal,
  });
  if (res.status === 401) onUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    onToken?.(decoder.decode(value, { stream: true }));
  }
}
