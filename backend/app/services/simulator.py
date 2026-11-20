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
from synthetic.generate import BAD_HEAT, LINES, SHIFTS, DEFECT_CODES, CAMERAS, LOCATIONS


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
        return {"running": self.running, "interval_sec": self.interval,
                "live_lots": [{"lot": v["lot"], "line": v["line"], "sampled": v["sampled"]} for v in self._lots.values()]}

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
        p = 0.06 + (0.12 if line["id"] == "L1" and shift == "C" else 0) + (BAD_HEAT["pitting_boost"] if bad_material else 0)
        if rng.random() < p:
            mix = {"L1": ["porosity", "scratch", "dent"], "L2": ["burr", "scratch", "dent"],
                   "L3": ["pitting", "scratch", "dent"]}[line["id"]]
            dtype = "pitting" if bad_material and rng.random() < 0.6 else rng.choice(mix)
            code = next(c for c in DEFECT_CODES if dtype in c["synonyms"])
            dets.append({"ts": now.isoformat(), "line": line["id"], "station": "ST3", "shift": shift, "lot": lot,
                         "part_serial": serial, "camera_id": CAMERAS[line["id"]], "defect_type": dtype,
                         "defect_code": code["code"], "confidence": round(rng.uniform(0.6, 0.99), 3),
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
