@echo off
cd /d %~dp0\..\backend
if not exist .venv (
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate
if exist ..\offline\wheels (
  pip install --no-index --find-links ..\offline\wheels -r requirements.txt -q
) else (
  pip install -r requirements.txt -q
)
if not exist .env copy .env.example .env
uvicorn app.main:app --reload --port 8000
