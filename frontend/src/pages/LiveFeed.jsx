import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorBox, Kpi, sevTone } from "../components/ui.jsx";

export default function LiveFeed({ can, navigate, notify }) {
  const [events, setEvents] = useState([]);
  const [sim, setSim] = useState(null);
  const [error, setError] = useState("");
  const [busyLot, setBusyLot] = useState("");
  const lastId = useRef(0);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const res = await api.live(lastId.current);
        if (stop) return;
        if (res.events.length) {
          lastId.current = res.events[res.events.length - 1].id;
          setEvents((e) => [...res.events.reverse(), ...e].slice(0, 200));
        }
        setSim(res.simulator);
        setError("");
      } catch (e) { if (!stop) setError(e.message); }
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const toggle = async () => {
    try { setSim(await api.simulator(sim?.running ? "stop" : "start")); }
    catch (e) { notify(e.message, "red"); }
  };

  const generate = async (lot) => {
    setBusyLot(lot);
    try { const rep = await api.generate(lot); navigate("report", rep.id); }
    catch (e) { notify(e.message, "red"); setBusyLot(""); }
  };

  // Totals are counted on the server since the backend started, so they only go up and survive a page
  // reload. The feed below shows just the newest 200 parts.
  const t = sim?.totals || { parts: 0, out_of_spec_parts: 0, detections: 0 };
  const parts = t.parts, oos = t.out_of_spec_parts, dets = t.detections;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Live Inspection</h1>
          <p className="muted">Real-time feed from camera and dimensional sensor systems (simulated inspection API).</p>
        </div>
        <div className="row">
          <Badge tone={sim?.running ? "green" : "neutral"}>{sim?.running ? "● Streaming" : "Paused"}</Badge>
          {can("simulator:control") && (
            <button className="ghost" onClick={toggle}>{sim?.running ? "Pause feed" : "Start feed"}</button>
          )}
        </div>
      </header>
      <ErrorBox error={error} />

      <div className="kpi-row">
        <Kpi label="Parts this session" value={parts.toLocaleString("en-US")} sub="since the feed started" />
        <Kpi label="Out-of-spec parts" value={oos} tone={oos ? "amber" : ""} sub={parts ? `${(100 * oos / parts).toFixed(1)}% of parts` : ""} />
        <Kpi label="Camera detections" value={dets} tone={dets ? "amber" : ""} sub={parts ? `${(100 * dets / parts).toFixed(1)} per 100 parts` : ""} />
        <Kpi label="Active lots" value={sim?.live_lots?.length ?? 0} />
      </div>

      <div className="grid-2-1">
        <Card title="Incoming parts" actions={<span className="muted small-text">newest 200 shown</span>}>
          {!events.length && <Empty>Waiting for parts… {sim && !sim.running && "The feed is paused."}</Empty>}
          <div className="feed">
            {events.map((e) => {
              const bad = e.measurements.filter((m) => !m.in_spec);
              return (
                <div key={e.id} className={`feed-item ${bad.length || e.detections.length ? "alert" : ""}`}>
                  <div className="feed-top">
                    <Badge>{e.line}</Badge>
                    <code>{e.part_serial}</code>
                    <span className="muted small-text">{e.ts.slice(11)}</span>
                  </div>
                  <div className="feed-body">
                    {e.measurements.map((m) => (
                      <span key={m.feature} className={`meas ${m.in_spec ? "" : "out"}`}
                            title={`limits ${m.lsl} – ${m.usl} ${m.unit}`}>
                        {m.feature}: <b>{m.value}</b> {m.unit}
                      </span>
                    ))}
                    {e.detections.map((d, i) => (
                      <Badge key={i} tone={sevTone(d.severity)}>
                        📷 {d.defect_code} {d.defect_type} ({Math.round(d.confidence * 100)}%)
                      </Badge>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <Card title="Lots in progress">
          {!sim?.live_lots?.length && <Empty>No live lots yet.</Empty>}
          {sim?.live_lots?.map((l) => (
            <div key={l.lot} className="lot-row">
              <div>
                <strong>{l.lot}</strong>
                <div className="muted small-text">{l.sampled} parts sampled so far · {l.out_of_spec_parts ?? 0} out of spec · {l.detections ?? 0} camera detections</div>
              </div>
              {can("report:generate") && (
                <button className="primary small" disabled={!!busyLot} onClick={() => generate(l.lot)}>
                  {busyLot === l.lot ? "Generating…" : "Generate report"}
                </button>
              )}
            </div>
          ))}
          <p className="muted small-text">Reports can be generated for a lot while it is still running; the shift-end
            deadline rule shows how much time is left.</p>
        </Card>
      </div>
    </div>
  );
}
