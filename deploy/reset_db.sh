#!/usr/bin/env bash
set -euo pipefail
# Pristine demo state: stop the API, drop the SQLite store, restart.
# The app recreates and re-seeds the schema at startup (seed_if_empty),
# so anyone opening the public demo link gets a clean data pack.
# Run on a timer (deploy/parcelpilot-reset.timer), every 10 minutes.
# Runs as root (systemd oneshot) — use an absolute path, not $HOME.
DB="/home/ec2-user/parcel-pilot-ai-assistant/data/store/parcelpilot.db"

systemctl stop parcelpilot
rm -f "$DB"
systemctl start parcelpilot
for i in $(seq 1 15); do
    if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "parcelpilot store reset ok ($(date -Is))"
        exit 0
    fi
    sleep 1
done
echo "parcelpilot store reset FAILED: service not healthy after restart" >&2
exit 1
