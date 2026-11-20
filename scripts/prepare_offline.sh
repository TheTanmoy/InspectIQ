#!/usr/bin/env bash
# Run on a machine WITH internet, same OS + Python version as the event machine.
set -e
cd "$(dirname "$0")/.."
pip download -r backend/requirements.txt -d offline/wheels
(cd frontend && npm install)
echo "Done. Copy the whole ai_friday_starter folder to the common folder."
