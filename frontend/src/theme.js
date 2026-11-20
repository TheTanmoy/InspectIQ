// Light / dark theme. The choice is remembered per browser (a viewer convenience, safe to lose).
const KEY = "inspectiq_theme";

export function getTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function initialTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch { /* storage blocked */ }
  return "dark"; // the product's signature look
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f3f5f8" : "#07080a");
  try { localStorage.setItem(KEY, theme); } catch { /* storage blocked */ }
}

// Chart / SVG colours are tuned for dark; these are their light-theme counterparts.
const LIGHT = {
  "#c9ced6": "#475569", "#4aa3e0": "#1d6fb5", "#e2ac45": "#b7791f", "#43c690": "#168a52", "#a98ce8": "#7c3aed",
  "#f0605d": "#d23f3b", "#737a85": "#64748b", "#8fc6ee": "#3b82c4", "#6db8ec": "#4a90d0", "#1f5a84": "#1d6fb5",
  "#4a5059": "#cbd5e1", "#0c0d10": "#ffffff",
};
/** theme colour: pass a dark-theme hex, get the right colour for the current theme */
export const tc = (c) => (getTheme() === "light" && c && LIGHT[c.toLowerCase()]) || c;
