#!/usr/bin/env bash
set -euo pipefail
# Pristine demo state: stop the API, drop the SQLite store, restart.
# The app recreates and re-seeds the schema at startup (seed_if_empty),
# so anyone opening the public demo link gets a clean data pack.
# Run on a timer (deploy/parcelpilot-reset.timer), every 10 minutes.
DB="$HOME/parcel-pilot-ai-assistant/data/store/parcelpilot.db"

systemctl stop parcelpilot
rm -f "$DB"
systemctl start parcelpilot
sleep 2
curl -fsS http://localhost:8000/api/health >/dev/null
echo "parcelpilot store reset ok ($(date -Is))"
