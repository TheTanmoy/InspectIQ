"""Inspection data source adapter.

The rest of the app only talks to `store` (a DataStore). Two implementations:
  - SyntheticSource: reads the generated CSV/JSON files + live events from the simulator (default)
  - HttpSource:      reads the same shapes from a real inspection-system REST API
Switch with INSPECTION_SOURCE=http://host:port in .env - no other code changes needed.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core import config

DATE_COLS = {"measurements": ["ts"], "detections": ["ts"], "manual_checks": ["ts"],
             "lots": ["shift_start", "shift_end"], "maintenance_log": ["ts"]}


def ensure_data(data_dir: Path = config.DATA_DIR) -> bool:
    """Generate synthetic data on first run. Returns True if it had to generate."""
    if (data_dir / "measurements.csv").exists() and (data_dir / "materials.csv").exists():
        return False
    from synthetic.generate import generate
    generate(out=data_dir)
    return True


class SyntheticSource:
    name = "synthetic"

    def __init__(self, data_dir: Path = config.DATA_DIR):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        self.reload()

    # ---------------------------------------------------------------- loading
    def reload(self):
        with self._lock:
            self.plant = json.loads((self.data_dir / "plant.json").read_text())
            self._base = {}
            for name, cols in DATE_COLS.items():
                df = pd.read_csv(self.data_dir / f"{name}.csv")
                for c in cols:
                    df[c] = pd.to_datetime(df[c])
                self._base[name] = df
            self._base["detections"]["image_id"] = self._base["detections"]["image_id"].fillna("").astype(str)
            self._base["manual_checks"]["notes"] = self._base["manual_checks"]["notes"].fillna("").astype(str)
            mpath = self.data_dir / "materials.csv"
            self._materials = _clean_materials(pd.read_csv(mpath) if mpath.exists() else pd.DataFrame())
            self._live = {"measurements": [], "detections": [], "manual_checks": [], "lots": {}}
            self._live_events: list[dict] = []
            self._event_seq = 0
            self._live_counts: dict[str, dict] = {}
            self._cache: dict[str, pd.DataFrame] = {}

    def _frame(self, name: str) -> pd.DataFrame:
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            base = self._base[name]
            live = list(self._live["lots"].values()) if name == "lots" else self._live.get(name, [])
            if live:
                extra = pd.DataFrame(live)
                for c in DATE_COLS.get(name, []):
                    extra[c] = pd.to_datetime(extra[c])
                if name == "lots":  # live lots replace stale copies
                    base = base[~base.lot.isin(extra.lot)]
                df = pd.concat([base, extra], ignore_index=True)
            else:
                df = base
            self._cache[name] = df
            return df

    # ---------------------------------------------------------------- queries
    def measurements(self) -> pd.DataFrame:
        return self._frame("measurements")

    def detections(self) -> pd.DataFrame:
        return self._frame("detections")

    def manual_checks(self) -> pd.DataFrame:
        return self._frame("manual_checks")

    def lots(self) -> pd.DataFrame:
        return self._frame("lots")

    def maintenance(self) -> pd.DataFrame:
        return self._base["maintenance_log"]

    # ---------------------------------------------------------------- raw material
    def materials(self) -> pd.DataFrame:
        return self._materials

    def material_specs(self) -> dict:
        return self.plant.get("materials", {})

    def material(self, material_lot) -> dict | None:
        """One raw-material lot with its certificate checked against the grade spec."""
        if not material_lot or self._materials.empty or (isinstance(material_lot, float) and pd.isna(material_lot)):
            return None
        rows = self._materials[self._materials.material_lot == material_lot]
        if rows.empty:
            return None
        r = rows.iloc[0].to_dict()
        spec = self.material_specs().get(r["line"], {}).get("spec", {})
        cert, deviations = [], []
        for prop, lim in spec.items():
            v = r.get(f"cert_{prop}")
            if v is None or pd.isna(v):
                continue
            ok = lim["min"] <= float(v) <= lim["max"]
            cert.append({"property": prop, "value": float(v), "min": lim["min"], "max": lim["max"], "in_spec": ok})
            if not ok:
                deviations.append(f"{prop} {float(v):g} (spec {lim['min']:g}-{lim['max']:g})")
        return {k: ("" if isinstance(r.get(k), float) and pd.isna(r.get(k)) else r.get(k))
                for k in ("material_lot", "line", "material", "form", "supplier", "heat_number", "received",
                          "first_used", "incoming_result", "deviation_ref")} | {"certificate": cert,
                                                                                "deviations": deviations}

    def current_material_lot(self, line_id: str) -> str:
        m = self._materials
        if m.empty:
            return ""
        m = m[m.line == line_id].sort_values("first_used")
        return str(m.material_lot.iloc[-1]) if not m.empty else ""

    def gauges(self) -> list[dict]:
        return self.plant["gauges"]

    def defect_codes(self) -> list[dict]:
        return self.plant["defect_codes"]

    def line(self, line_id: str) -> dict | None:
        return next((ln for ln in self.plant["lines"] if ln["id"] == line_id), None)

    def image_path(self, image_id: str) -> Path | None:
        p = self.data_dir / "images" / f"{Path(image_id).name}.png"
        return p if p.exists() else None

    def legacy_reports(self) -> list[tuple[str, str]]:
        folder = self.data_dir / "legacy_reports"
        return [(p.name, p.read_text()) for p in sorted(folder.glob("*.txt"))] if folder.exists() else []

    # ---------------------------------------------------------------- live (simulator)
    def add_live(self, measurements: list[dict], detections: list[dict], lot_row: dict) -> dict:
        with self._lock:
            self._live["measurements"].extend(measurements)
            self._live["detections"].extend(detections)
            self._live["lots"][lot_row["lot"]] = lot_row
            self._cache.clear()
            self._event_seq += 1
            event = {"id": self._event_seq, "ts": datetime.now().replace(microsecond=0).isoformat(),
                     "line": lot_row["line"], "lot": lot_row["lot"],
                     "part_serial": measurements[0]["part_serial"] if measurements else "",
                     "measurements": [{k: m[k] for k in ("feature", "value", "lsl", "usl", "unit", "in_spec")}
                                      for m in measurements],
                     "detections": [{k: d[k] for k in ("defect_code", "defect_type", "confidence", "severity", "location")}
                                    for d in detections]}
            self._live_events.append(event)
            self._live_events = self._live_events[-500:]
            c = self._live_counts.setdefault(lot_row["lot"], {"parts": 0, "out_of_spec_parts": 0, "detections": 0})
            c["parts"] += len({m["part_serial"] for m in measurements}) or 1
            c["out_of_spec_parts"] += len({m["part_serial"] for m in measurements if not m["in_spec"]})
            c["detections"] += len(detections)
            return event

    def live_stats(self) -> dict:
        """Running totals since the backend started: per lot and for the whole session."""
        with self._lock:
            lots = {k: dict(v) for k, v in self._live_counts.items()}
        totals = {k: sum(v[k] for v in lots.values()) for k in ("parts", "out_of_spec_parts", "detections")}
        return {"lots": lots, "totals": totals}

    def live_events(self, since_id: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self._live_events if e["id"] > since_id]


class HttpSource(SyntheticSource):
    """Same interface, data pulled from a real inspection API exposing:
    GET /measurements, /detections, /manual_checks, /lots, /maintenance_log, /plant  (JSON lists / object),
    optionally /materials (raw-material lots; lots then carry a material_lot field).
    Kept minimal on purpose - adapt field names here if the real API differs."""
    name = "http"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        super().__init__()

    def reload(self):
        import requests
        with self._lock:
            get = lambda p: requests.get(f"{self.base_url}/{p}", timeout=30, verify=config.VERIFY_SSL).json()
            self.plant = get("plant")
            self._base = {}
            for name, cols in DATE_COLS.items():
                df = pd.DataFrame(get(name))
                for c in cols:
                    if c in df:
                        df[c] = pd.to_datetime(df[c])
                self._base[name] = df
            try:  # optional endpoint - older inspection APIs may not expose raw-material data
                self._materials = _clean_materials(pd.DataFrame(get("materials")))
            except Exception:
                self._materials = _clean_materials(pd.DataFrame())
            self._live = {"measurements": [], "detections": [], "manual_checks": [], "lots": {}}
            self._live_events, self._event_seq, self._cache, self._live_counts = [], 0, {}, {}

    def image_path(self, image_id: str):
        return None


def _clean_materials(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["material_lot", "line", "supplier", "heat_number", "first_used",
                                     "incoming_result", "deviation_ref"])
    df["deviation_ref"] = df["deviation_ref"].fillna("").astype(str)
    return df


_store: SyntheticSource | None = None


def get_store() -> SyntheticSource:
    global _store
    if _store is None:
        if config.INSPECTION_SOURCE.startswith("http"):
            _store = HttpSource(config.INSPECTION_SOURCE)
        else:
            ensure_data()
            _store = SyntheticSource()
    return _store


def set_store(store: SyntheticSource):
    global _store
    _store = store
