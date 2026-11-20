"""InspectIQ - AI quality inspection report generator (FastAPI backend).

Run (from backend/):  uvicorn app.main:app --reload --port 8000
API docs:            http://localhost:8000/docs
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import analytics, assistant, audit as audit_api, auth, compliance as compliance_api, finops, inspection, quality_cost, reports
from app.core import config, db, security
from app.core.llm import LLMError
from app.services import compliance
from app.services.ai import RateLimited
from app.services.inspection_source import ensure_data, get_store
from app.services.reports import WorkflowError
from app.services.simulator import get_simulator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("inspectiq")


def startup():
    if ensure_data():
        log.info("Synthetic data generated in %s", config.DATA_DIR)
    db.conn()
    security.seed_users(json.loads((config.DATA_DIR / "users.json").read_text()))
    compliance.seed_rules()
    store = get_store()
    if config.SIMULATOR_ENABLED:
        get_simulator(store).start()
    log.info("InspectIQ ready - LLM provider: %s, model: %s%s", config.LLM_PROVIDER, config.LLM_MODEL,
             f" (fallback: {config.LLM_FALLBACK_MODEL})" if config.LLM_FALLBACK_MODEL else "")


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield
    get_simulator().stop()


app = FastAPI(title="InspectIQ API", version="1.1.2", lifespan=lifespan,
              description="Automated manufacturing quality inspection reports with GenAI, guardrails, "
                          "editable compliance rules, role-based access and audit logging. All data is synthetic.")

app.add_middleware(CORSMiddleware, allow_origins=config.get("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api") and not request.url.path.startswith("/api/inspection/live"):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000)
    return response


# ---------------------------------------------------------------- friendly errors (basic error handling)
def _err(status: int, msg: str):
    return JSONResponse(status_code=status, content={"detail": msg})


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, exc: WorkflowError):
    return _err(409, str(exc))


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return _err(400, str(exc))


@app.exception_handler(KeyError)
async def key_error(_: Request, exc: KeyError):
    return _err(404, f"Not found: {str(exc).strip(chr(39))}")


@app.exception_handler(RateLimited)
async def rate_limited(_: Request, exc: RateLimited):
    return _err(429, str(exc))


@app.exception_handler(LLMError)
async def llm_error(_: Request, exc: LLMError):
    return _err(502, f"AI service error: {exc}")


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception):
    log.exception("Unexpected error")
    return _err(500, "Something went wrong on the server. The error has been logged.")


for r in (auth.router, inspection.router, reports.router, analytics.router, compliance_api.router,
          audit_api.router, assistant.router, finops.router, quality_cost.router):
    app.include_router(r)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "app": config.APP_TITLE, "llm_provider": config.LLM_PROVIDER, "model": config.LLM_MODEL,
            "fallback_model": config.LLM_FALLBACK_MODEL,
            "vision": config.LLM_VISION, "data_source": get_store().name,
            "simulator": get_simulator().status()["running"], "rulebook_version": compliance.rulebook_version()}


# ---------------------------------------------------------------- serve the built React app (single-port demo)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        return FileResponse(target if path and target.is_file() else DIST / "index.html")
