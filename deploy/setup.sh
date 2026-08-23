#!/usr/bin/env bash
set -euo pipefail
# One-time EC2 setup (Amazon Linux 2023): deps, venv, systemd service.
REPO_URL="https://github.com/artzuros/parcel-pilot-ai-assistant.git"
REPO="$HOME/parcel-pilot-ai-assistant"

sudo dnf install -y git python3-pip

# Cloudflare Tunnel client (outbound-only ingress for the API)
if ! command -v cloudflared >/dev/null 2>&1; then
  sudo dnf install -y \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-x86_64.rpm
fi

if [ ! -d "$REPO" ]; then
  git clone "$REPO_URL" "$REPO"
fi

cd "$REPO/backend"
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

if [ ! -f /etc/parcelpilot.env ]; then
  sudo touch /etc/parcelpilot.env
  sudo chmod 600 /etc/parcelpilot.env
  echo "==> create /etc/parcelpilot.env with: DEEPSEEK_API_KEY=sk-... (sudo nano)"
fi

sudo cp "$REPO/deploy/parcelpilot.service" /etc/systemd/system/parcelpilot.service
sudo systemctl daemon-reload
sudo systemctl enable --now parcelpilot
sleep 3
curl -s http://localhost:8000/api/health && echo " <- health OK"
