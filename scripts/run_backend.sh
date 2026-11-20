#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../backend"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
if [ -d ../offline/wheels ]; then pip install --no-index --find-links ../offline/wheels -r requirements.txt -q
else pip install -r requirements.txt -q; fi
[ -f .env ] || cp .env.example .env
uvicorn app.main:app --reload --port 8000
