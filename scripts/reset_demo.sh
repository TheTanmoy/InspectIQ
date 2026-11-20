#!/usr/bin/env bash
# Stop the backend first. Deletes the demo database and synthetic data; both are recreated on next start.
cd "$(dirname "$0")/../backend" && rm -rf inspectiq.db data && echo "Demo reset. Start the backend again."
