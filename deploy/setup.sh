#!/usr/bin/env bash
set -euo pipefail
# One-time EC2 setup: deps, venv, systemd service. Run as ubuntu, once.
REPO_URL="https://github.com/artzuros/parcel-pilot-ai-assistant.git"
REPO="$HOME/parcel-pilot-ai-assistant"

sudo apt-get update -y
sudo apt-get install -y git python3-venv python3-pip

# Cloudflare Tunnel client (outbound-only ingress for the API)
if ! command -v cloudflared >/dev/null 2>&1; then
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y cloudflared
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
curl -s http://localhost/api/health && echo " <- health OK"
