"""Inspection data API (synthetic stand-in for the plant's camera / sensor / checklist systems)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import require
from app.core import audit
from app.services.inspection_source import get_store
from app.services.simulator import get_simulator

router = APIRouter(prefix="/api/inspection", tags=["inspection data"])
VIEW = Depends(require("inspection:view"))


def _records(df, limit: int):
    df = df.tail(limit).copy()
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime"):
            df[c] = df[c].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return df.where(df.notna(), None).to_dict(orient="records")


@router.get("/plant")
def plant(user=VIEW):
    return get_store().plant


@router.get("/lots")
def lots(line: str = "", limit: int = Query(60, le=1000), user=VIEW):
    df = get_store().lots().sort_values("shift_end")
    if line:
        df = df[df.line == line]
    df = df.assign(in_progress=df.shift_end > datetime.now())
    return list(reversed(_records(df, limit)))


@router.get("/measurements")
def measurements(lot: str = "", line: str = "", limit: int = Query(500, le=5000), user=VIEW):
    df = get_store().measurements()
    df = df[df.lot == lot] if lot else df[df.line == line] if line else df
    return _records(df, limit)


@router.get("/detections")
def detections(lot: str = "", line: str = "", limit: int = Query(200, le=5000), user=VIEW):
    df = get_store().detections()
    df = df[df.lot == lot] if lot else df[df.line == line] if line else df
    return _records(df, limit)


@router.get("/manual-checks")
def manual_checks(lot: str, user=VIEW):
    df = get_store().manual_checks()
    return _records(df[df.lot == lot], 200)


@router.get("/gauges")
def gauges(user=VIEW):
    return get_store().gauges()


@router.get("/images/{image_id}")
def image(image_id: str, user=VIEW):
    path = get_store().image_path(image_id)
    if not path:
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@router.get("/live")
def live(since: int = 0, user=VIEW):
    store = get_store()
    return {"events": store.live_events(since), "simulator": get_simulator(store).status()}


@router.post("/simulator/{action}")
def simulator(action: str, user=Depends(require("simulator:control"))):
    sim = get_simulator()
    if action == "start":
        sim.start()
    elif action == "stop":
        sim.stop()
    else:
        raise HTTPException(400, "action must be start or stop")
    audit.log(user, f"simulator.{action}", "simulator", "live")
    return sim.status()
