#!/usr/bin/env bash
set -euo pipefail
# Pull latest main and restart the service. Run on every update.
cd "$HOME/parcel-pilot-ai-assistant"
git pull --ff-only origin main
cd backend
./.venv/bin/pip install -r requirements.txt --quiet
sudo systemctl restart parcelpilot
sleep 3
curl -s http://localhost/api/health && echo " <- health OK"
