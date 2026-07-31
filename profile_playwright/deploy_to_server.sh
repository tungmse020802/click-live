#!/usr/bin/env bash
# Deploy profile_playwright (deeplink API + browser profile) lên VPS.
#
# Usage:
#   cd profile_playwright
#   SERVER_PASS='...' bash deploy_to_server.sh
#
# Env:
#   SERVER_HOST=160.30.19.215
#   SERVER_USER=root
#   REMOTE_DIR=/root/click-live/profile_playwright

set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
REMOTE_DIR="${REMOTE_DIR:-/root/click-live/profile_playwright}"

SERVER_HOST="${SERVER_HOST:-160.30.19.215}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PASS="${SERVER_PASS:-}"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "Cần sshpass. macOS: brew install sshpass" >&2
  exit 1
fi

if [[ -z "$SERVER_PASS" ]]; then
  read -r -s -p "SSH password for ${SERVER_USER}@${SERVER_HOST}: " SERVER_PASS
  echo
fi

SSH_OPTS=(-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no)
SSH=(sshpass -p "$SERVER_PASS" ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_HOST}")
RSYNC_SSH="sshpass -p ${SERVER_PASS} ssh ${SSH_OPTS[*]}"

echo "==> Rsync profile_playwright -> ${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}"
rsync -az \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'auth_analysis.json' \
  --exclude 'junb_resolve_result.json' \
  --exclude 'analyze_auth.py' \
  --exclude 'resolve_junb.py' \
  --exclude 'bench_api.py' \
  -e "$RSYNC_SSH" \
  "$ROOT_DIR/" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

echo "==> Install systemd service"
"${SSH[@]}" bash -s <<REMOTE_SETUP
set -euo pipefail
cd "${REMOTE_DIR}"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="${REMOTE_DIR}/.pw-browsers"
.venv/bin/playwright install chromium
mkdir -p systemd
REMOTE_SETUP
"${SSH[@]}" "cp ${REMOTE_DIR}/systemd/click-live-deeplink-api.service /etc/systemd/system/click-live-deeplink-api.service"
"${SSH[@]}" "systemctl daemon-reload"
"${SSH[@]}" "systemctl enable click-live-deeplink-api.service"
"${SSH[@]}" "systemctl restart click-live-deeplink-api.service"
sleep 1
"${SSH[@]}" "systemctl is-active click-live-deeplink-api.service"

echo "==> Health check"
"${SSH[@]}" "curl -s http://127.0.0.1:8792/health"
echo
"${SSH[@]}" "curl -s --get http://127.0.0.1:8792/api/deeplink --data-urlencode 'url=https://thanhtai.io/r/b7YVmORSncRD4'"
echo
"${SSH[@]}" "curl -s --get http://127.0.0.1:8792/api/deeplink --data-urlencode 'url=https://thanhtai.io/r/f4cb4b1649bf'"
echo
echo "Done. API: http://${SERVER_HOST}:8792/api/deeplink"
