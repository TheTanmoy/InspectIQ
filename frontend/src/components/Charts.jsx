import { tc } from "../theme.js";
// Dependency-free SVG charts (no chart library needed - works offline).

// tuned for the dark theme: brushed silver, signal blue, amber, green, violet
export const PALETTE = ["#c9ced6", "#4aa3e0", "#e2ac45", "#43c690", "#a98ce8"];
const RED = "#f0605d";

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + i * step);
}

// decimals chosen from the tick step, so narrow ranges (e.g. 29.985-30.015 mm) stay readable
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const fmtFor = (min, max) => {
  if (Math.max(Math.abs(min), Math.abs(max)) >= 10000) return (v) => compact.format(v);
  const step = Math.abs(max - min) / 4 || 1;
  const d = Math.min(5, Math.max(0, Math.ceil(-Math.log10(step)) + 1));
  return (v) => v.toFixed(d);
};

/**
 * series: [{ name, color?, points: [{ x: "2026-11-01", y: 1.2 }] }]
 * refLines: [{ y, label, color, dash }]
 */
export function LineChart({ series, refLines = [], height = 240, yLabel = "", xEvery }) {
  const W = 720, H = height, P = { l: 62, r: 16, t: 14, b: 34 };
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort();
  if (!xs.length) return <div className="muted small-text">No data.</div>;
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).concat(refLines.map((r) => r.y)).filter((v) => v != null);
  let min = Math.min(...ys), max = Math.max(...ys);
  const allPositive = min >= 0;
  const pad = (max - min) * 0.08 || Math.abs(max) * 0.05 || 1;
  min -= pad; max += pad;
  if (allPositive && min < 0) min = 0;
  const fmt = fmtFor(min, max);
  const x = (i) => P.l + (xs.length === 1 ? 0.5 : i / (xs.length - 1)) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
  const every = xEvery || Math.max(1, Math.ceil(xs.length / 8));
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={yLabel || "line chart"}>
        {niceTicks(min, max).map((t, i) => (
          <g key={i}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={P.l - 6} y={y(t) + 4} textAnchor="end" className="tick">{fmt(t)}</text>
          </g>
        ))}
        {xs.map((v, i) => i % every === 0 && (
          <text key={v} x={x(i)} y={H - 12} textAnchor="middle" className="tick">{String(v).slice(5, 10)}</text>
        ))}
        {yLabel && <text x={12} y={P.t + 4} className="tick" transform={`rotate(-90 12 ${P.t + 4})`} textAnchor="end">{yLabel}</text>}
        {refLines.map((r, i) => (
          <g key={`r${i}`}>
            <line x1={P.l} x2={W - P.r} y1={y(r.y)} y2={y(r.y)} stroke={tc(r.color || RED)}
                  strokeDasharray={r.dash ? "5 4" : ""} strokeWidth="1.4" />
            <text x={W - P.r - 4} y={y(r.y) - 4} textAnchor="end" className="ref-label" fill={tc(r.color || RED)}>{r.label}</text>
          </g>
        ))}
        {series.map((s, si) => {
          const color = tc(s.color || PALETTE[si % PALETTE.length]);
          const pts = s.points.map((p) => [x(xs.indexOf(p.x)), y(p.y), p]);
          return (
            <g key={s.name}>
              <polyline fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" points={pts.map(([a, b]) => `${a},${b}`).join(" ")} />
              {pts.map(([a, b, p]) => (
                <circle key={p.x} cx={a} cy={b} r="2.2" fill={tc("#0c0d10")} stroke={color} strokeWidth="1.3">
                  <title>{`${s.name} · ${p.x}: ${p.y}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s, i) => (
            <span key={s.name}><i style={{ background: tc(s.color || PALETTE[i % PALETTE.length]) }} />{s.name}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Pareto: bars (count) + cumulative % line. data: [{ label, value, cum }] */
export function ParetoChart({ data, height = 240 }) {
  const W = 720, H = height, P = { l: 44, r: 44, t: 14, b: 44 };
  if (!data.length) return <div className="muted small-text">No defects in this window.</div>;
  const max = Math.max(...data.map((d) => d.value)) * 1.1;
  const bw = (W - P.l - P.r) / data.length;
  const y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  const yc = (v) => P.t + (1 - v / 100) * (H - P.t - P.b);
  const cx = (i) => P.l + bw * i + bw / 2;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="pareto chart">
        <defs>
          <linearGradient id="bar-blue" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={tc("#6db8ec")} /><stop offset="1" stopColor={tc("#1f5a84")} /></linearGradient>
          <linearGradient id="bar-silver" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={tc("#c9ced6")} /><stop offset="1" stopColor={tc("#4a5059")} /></linearGradient>
        </defs>
        {niceTicks(0, max).map((t, i) => (
          <g key={i}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={P.l - 6} y={y(t) + 4} textAnchor="end" className="tick">{Math.round(t)}</text>
          </g>
        ))}
        {[0, 50, 80, 100].map((t) => (
          <text key={t} x={W - P.r + 6} y={yc(t) + 4} className="tick">{t}%</text>
        ))}
        <line x1={P.l} x2={W - P.r} y1={yc(80)} y2={yc(80)} stroke={tc("#4a5059")} strokeDasharray="4 4" />
        {data.map((d, i) => (
          <g key={d.label}>
            <rect x={P.l + bw * i + bw * 0.15} y={y(d.value)} width={bw * 0.7} height={H - P.b - y(d.value)}
                  rx="2" fill={i === 0 ? "url(#bar-blue)" : "url(#bar-silver)"}>
              <title>{`${d.label}: ${d.value}`}</title>
            </rect>
            <text x={cx(i)} y={y(d.value) - 5} textAnchor="middle" className="tick strong">{d.value}</text>
            <text x={cx(i)} y={H - P.b + 16} textAnchor="middle" className="tick">{d.label}</text>
          </g>
        ))}
        <polyline fill="none" stroke={tc("#e2ac45")} strokeWidth="1.6" points={data.map((d, i) => `${cx(i)},${yc(d.cum)}`).join(" ")} />
        {data.map((d, i) => <circle key={i} cx={cx(i)} cy={yc(d.cum)} r="2.6" fill={tc("#e2ac45")}><title>{`${d.cum}% cumulative`}</title></circle>)}
      </svg>
    </div>
  );
}

/** Simple horizontal bars, e.g. defects per 100 parts by shift. */
export function HBars({ data, unit = "", max }) {
  const m = max || Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="hbars">
      {data.map((d) => (
        <div key={d.label} className="hbar-row">
          <span className="hbar-label">{d.label}</span>
          <span className="hbar-track">
            <span className={`hbar-fill ${d.tone || ""}`} style={{ width: `${(100 * d.value) / m}%` }} />
          </span>
          <span className="hbar-val">{d.value}{unit}</span>
        </div>
      ))}
    </div>
  );
}
