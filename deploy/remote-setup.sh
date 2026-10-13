#!/usr/bin/env bash
# Runs on a fresh Ubuntu 24.04 Droplet as root (deploy/deploy.sh copies it over and runs it).
# SlopGate under systemd, behind Caddy with automatic HTTPS. Safe to run again to update.
#   bash remote-setup.sh 203-0-113-5.sslip.io
set -euo pipefail
HOST="${1:?usage: remote-setup.sh HOSTNAME}"
APP=/opt/slopgate
export DEBIAN_FRONTEND=noninteractive

if ! command -v caddy >/dev/null; then
  apt-get update -q
  apt-get install -y -q git curl gnupg ca-certificates debian-keyring debian-archive-keyring apt-transport-https ufw
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  curl -fsSL https://deb.nodesource.com/setup_24.x | bash -   # anti-slop runs on Node 24
  apt-get install -y -q caddy nodejs
fi
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

id slopgate >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin slopgate
install -d -o slopgate -g slopgate "$APP"
as_app() { sudo -u slopgate -H "$@"; }
if [ -d "$APP/app/.git" ]; then as_app git -C "$APP/app" pull -q; else as_app git clone -q https://github.com/CTAGRAM/slopgate "$APP/app"; fi
[ -d "$APP/anti-slop" ] || as_app git clone -q --depth 1 https://github.com/peakoss/anti-slop "$APP/anti-slop"
(cd "$APP/app" && as_app uv sync --frozen --no-dev -q)

cat > /etc/systemd/system/slopgate.service <<EOF
[Unit]
Description=SlopGate
After=network-online.target

[Service]
User=slopgate
WorkingDirectory=$APP/app
EnvironmentFile=/etc/slopgate.env
Environment=ANTISLOP_DIR=$APP/anti-slop
ExecStart=$APP/app/.venv/bin/uvicorn slopgate.server:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/caddy/Caddyfile <<EOF
$HOST {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
EOF

ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ufw --force enable >/dev/null
systemctl daemon-reload
systemctl enable --now slopgate >/dev/null 2>&1
systemctl restart slopgate caddy
sleep 3
curl -fsS http://127.0.0.1:8000/healthz && echo
echo "SlopGate is up at https://$HOST"
