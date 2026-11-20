// Thin-line icons and the InspectIQ mark (original artwork, no third-party logos).

const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round" };

export function Logo() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="iq-silver" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: "var(--logo-a)" }} /><stop offset=".5" style={{ stopColor: "var(--logo-b)" }} /><stop offset="1" style={{ stopColor: "var(--logo-c)" }} />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="29" fill="none" stroke="url(#iq-silver)" strokeWidth="2" />
      <circle cx="32" cy="32" r="20" fill="none" stroke="url(#iq-silver)" strokeWidth="1" opacity=".55" />
      {/* aperture blades - an inspection lens */}
      <path d="M32 12 L38 26 M52 32 L38 38 M32 52 L26 38 M12 32 L26 26" stroke="url(#iq-silver)" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="32" cy="32" r="6.5" fill="none" style={{ stroke: "var(--logo-core)" }} strokeWidth="1.6" />
      <circle cx="32" cy="32" r="2" style={{ fill: "var(--logo-dot)" }} />
    </svg>
  );
}

const paths = {
  live: <><circle cx="12" cy="12" r="2.2" /><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" /></>,
  reports: <><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M10 12h5M10 16h5" /></>,
  dashboard: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
  compliance: <><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  audit: <><path d="M4 6h16M4 12h16M4 18h10" /><circle cx="19" cy="18" r="2" /></>,
  assistant: <><path d="M4 5h16v11H9l-5 4z" /><path d="M9 10h.01M12 10h.01M15 10h.01" /></>,
  value: <><path d="M3 17l5-5 4 4 8-8" /><path d="M15 8h5v5" /></>,
  qcost: <><path d="M4 20h16" /><path d="M6 20V9l4 3V9l4 3V5l4 3v12" /><path d="M9 16h.01M13 16h.01M17 16h.01" /></>,
  finops: <><circle cx="12" cy="12" r="8" /><path d="M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.4 0-2.5.8-2.5 2s1.1 1.7 2.5 2 2.5.8 2.5 2-1.1 2-2.5 2c-1 0-2-.5-2.5-1.5M12 6.5v1.5M12 16v1.5" /></>,
};

export function SunMoon({ theme }) {
  return theme === "light"
    ? <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
    : <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>;
}

/** Light / dark switch. The label says which theme is active. */
export function ThemeToggle({ theme, onToggle, floating = false }) {
  const next = theme === "light" ? "dark" : "light";
  return (
    <button type="button" className={`theme-toggle ${floating ? "floating" : ""}`} onClick={onToggle}
            aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      <SunMoon theme={theme} /> {theme === "light" ? "Light" : "Dark"} mode <span className="track"><i /></span>
    </button>
  );
}

export function Icon({ name }) {
  return <svg viewBox="0 0 24 24" {...base} aria-hidden="true">{paths[name]}</svg>;
}
