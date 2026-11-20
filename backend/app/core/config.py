"""Central config. Everything comes from backend/.env so swapping the LLM on the day = editing one file."""
import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except ImportError:  # dotenv is optional; plain environment variables also work
    pass


def get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ---- LLM: openai | azure | anthropic | gemini | mock
LLM_PROVIDER = get("LLM_PROVIDER", "mock").lower()
LLM_API_KEY = get("LLM_API_KEY")
LLM_BASE_URL = get("LLM_BASE_URL")
LLM_MODEL = get("LLM_MODEL", "gpt-4o-mini")  # for Azure this is the deployment name
# Optional second model, used automatically when the primary model fails or times out
LLM_FALLBACK_MODEL = get("LLM_FALLBACK_MODEL", "")
# Timeout for the primary model when a fallback exists (fail over quickly instead of waiting LLM_TIMEOUT)
LLM_PRIMARY_TIMEOUT = int(get("LLM_PRIMARY_TIMEOUT", get("LLM_TIMEOUT", "90")))
AZURE_API_VERSION = get("AZURE_API_VERSION", "2024-06-01")
LLM_VISION = get("LLM_VISION", "false").lower() == "true"  # set true if the provided model accepts images

LLM_TEMPERATURE = float(get("LLM_TEMPERATURE", "0.2"))
REPORT_TEMPERATURE = float(get("REPORT_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(get("LLM_MAX_TOKENS", "2000"))
LLM_TIMEOUT = int(get("LLM_TIMEOUT", "90"))
VERIFY_SSL = get("VERIFY_SSL", "true").lower() != "false"
LLM_RATE_LIMIT_PER_MIN = int(get("LLM_RATE_LIMIT_PER_MIN", "20"))
PROMPT_VERSION = "v1.0"

# ---- App
APP_TITLE = get("APP_TITLE", "InspectIQ")
SECRET_KEY = get("SECRET_KEY") or secrets.token_hex(32)  # set in .env so logins survive restarts
TOKEN_HOURS = int(get("TOKEN_HOURS", "12"))
DATA_DIR = Path(get("DATA_DIR") or (BACKEND_DIR / "data"))
DB_PATH = Path(get("DB_PATH") or (BACKEND_DIR / "inspectiq.db"))
SIMULATOR_ENABLED = get("SIMULATOR_ENABLED", "true").lower() == "true"
SIMULATOR_INTERVAL_SEC = float(get("SIMULATOR_INTERVAL_SEC", "3"))

# ---- Inspection data source: "synthetic" (local files) or an http base URL of a real inspection API
INSPECTION_SOURCE = get("INSPECTION_SOURCE", "synthetic")
