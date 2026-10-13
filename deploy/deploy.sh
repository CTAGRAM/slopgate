#!/usr/bin/env bash
# Deploy (or update) SlopGate on a DigitalOcean Droplet over SSH. No API token needed.
#   deploy/deploy.sh 203.0.113.5
# Reads secrets from .env.local and sends only what the server needs.
set -euo pipefail
IP="${1:?usage: deploy/deploy.sh DROPLET_IP}"
KEY="${SSH_KEY:-$HOME/.ssh/slopgate_do}"
HOST="${IP//./-}.sslip.io"   # a free hostname that resolves to the Droplet, so Caddy can get a certificate
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "root@$IP")
cd "$(dirname "$0")/.."

get() { grep -E "^$1=" .env.local | tail -1 | cut -d= -f2-; }
token="$(get DEPLOY_GITHUB_TOKEN)"
[ -n "$token" ] || { echo "add DEPLOY_GITHUB_TOKEN to .env.local first" >&2; exit 1; }
{
  echo "CODIV_API_KEY=$(get CODIV_API_KEY)"
  echo "GITHUB_TOKEN=$token"
  echo "GITHUB_WEBHOOK_SECRET=$(get GITHUB_WEBHOOK_SECRET)"
  echo "SLOPGATE_JUDGE_ALL_AUTHORS=$(get SLOPGATE_JUDGE_ALL_AUTHORS)"
} | "${SSH[@]}" 'umask 077 && cat > /etc/slopgate.env'

"${SSH[@]}" 'bash -s' "$HOST" < deploy/remote-setup.sh
echo "Arena:   https://$HOST"
echo "Webhook: https://$HOST/webhook"
