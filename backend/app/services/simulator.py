"""Live inspection simulator: pretends to be the camera + sensor systems streaming new parts in real time.

Each tick creates one inspected part on a random line (all features measured, sometimes a camera detection),
attached to the lot of the shift that is running right now. The Live Feed page polls these events, and reports
can be generated for the in-progress lot.
"""
from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime, timedelta

from app.core import config
from synthetic.generate import BAD_HEAT, CAMERAS, DEFECT_CODES, LINES, LOCATIONS, PROCESS_SPIKE, SHIFTS


def _current_shift(now: datetime) -> tuple[str, datetime, datetime]:
    for shift, (s, e) in SHIFTS.items():
        day = now.date() if not (shift == "C" and now.hour < 6) else (now - timedelta(days=1)).date()
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=s)
        end = datetime.combine(day, datetime.min.time()) + timedelta(hours=e)
        if start <= now < end:
            return shift, start, end
    raise RuntimeError("no shift")  # pragma: no cover


class Simulator:
    def __init__(self, store, interval: float = config.SIMULATOR_INTERVAL_SEC):
        self.store = store
        self.interval = interval
        self.running = False
        self._thread: threading.Thread | None = None
        self._rng = random.Random(7)
        self._lots: dict[str, dict] = {}
        self._serial = 0

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="inspection-simulator")
        self._thread.start()

    def stop(self):
        self.running = False

    def status(self) -> dict:
        stats = self.store.live_stats()
        lots = [{"lot": v["lot"], "line": v["line"], "shift": v["shift"], "sampled": v["sampled"],
                 **stats["lots"].get(v["lot"], {"parts": 0, "out_of_spec_parts": 0, "detections": 0})}
                for v in sorted(self._lots.values(), key=lambda x: (x["shift_start"], x["line"]), reverse=True)]
        return {"running": self.running, "interval_sec": self.interval, "live_lots": lots, "totals": stats["totals"]}

    def _loop(self):
        while self.running:
            try:
                self.tick()
            except Exception as e:  # never let the simulator kill the server
                print("simulator error:", e)
            time.sleep(self.interval)

    def tick(self, now: datetime | None = None) -> dict:
        rng = self._rng
        now = (now or datetime.now()).replace(microsecond=0)
        line = rng.choice(LINES)
        shift, start, end = _current_shift(now)
        lot = f"LOT-{line['id']}-{start:%y%m%d}-{shift}"
        lot_row = self._lots.get(lot) or {"lot": lot, "line": line["id"], "date": start.date().isoformat(),
                                          "shift": shift, "shift_start": start.isoformat(), "shift_end": end.isoformat(),
                                          "lot_size": rng.randint(400, 1100), "sampled": 0,
                                          "material_lot": self.store.current_material_lot(line["id"])}
        lot_row["sampled"] += 1
        self._lots[lot] = lot_row
        self._serial += 1
        serial = f"{line['prefix']}-{start:%y%m%d}-L{self._serial:04d}"
        meas = []
        for f in line["features"]:
            mean = f["nominal"]
            if line["id"] == "L3" and f["feature"] == "rod_diameter":
                mean += 0.011  # drift continues
            val = rng.gauss(mean, f["sigma"])
            if f["lsl"] == 0.0:
                val = abs(val)
            val = round(val, 4)
            meas.append({"ts": now.isoformat(), "line": line["id"], "station": f["station"], "shift": shift,
                         "lot": lot, "part_serial": serial, "feature": f["feature"], "value": val,
                         "nominal": f["nominal"], "lsl": f["lsl"], "usl": f["usl"], "unit": f["unit"],
                         "gauge_id": f["gauge"], "in_spec": f["lsl"] <= val <= f["usl"]})
        dets = []
        material = self.store.material(lot_row["material_lot"]) or {}
        bad_material = bool(material.get("deviations"))  # the planted bad heat is still in use on L3
        # Same rates as the 60-day history (synthetic/generate.py), so live parts do not create false spikes:
        # the line's base defect rate, plus the planted process spike and the bad material heat while they last.
        spike = line["id"] == PROCESS_SPIKE["line"] and shift == PROCESS_SPIKE["shift"]
        p = line["defect_rate"] + (PROCESS_SPIKE["boost"] if spike else 0) + (BAD_HEAT["pitting_boost"] if bad_material else 0)
        if rng.random() < p:
            if spike and rng.random() < PROCESS_SPIKE["share"]:
                dtype = "porosity"
            elif bad_material and rng.random() < 0.85:
                dtype = "pitting"
            else:
                mix = line["defect_mix"]
                dtype = rng.choices(list(mix), weights=list(mix.values()))[0]
            code = next(c for c in DEFECT_CODES if dtype in c["synonyms"])
            dets.append({"ts": now.isoformat(), "line": line["id"], "station": "ST3", "shift": shift, "lot": lot,
                         "part_serial": serial, "camera_id": CAMERAS[line["id"]], "defect_type": dtype,
                         "defect_code": code["code"], "confidence": round(min(max(rng.betavariate(8, 1.6), 0.5), 0.995), 3),
                         "severity": code["default_severity"], "location": rng.choice(LOCATIONS),
                         "bbox": json.dumps([100, 100, 30, 30]), "image_id": ""})
        return self.store.add_live(meas, dets, lot_row)


_sim: Simulator | None = None


def get_simulator(store=None) -> Simulator:
    global _sim
    if _sim is None:
        from app.services.inspection_source import get_store
        _sim = Simulator(store or get_store())
    return _sim
