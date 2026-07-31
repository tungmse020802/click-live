#!/usr/bin/env bash
# Cloudflare Quick Tunnel — VPS outbound → global HTTPS URL (phones abroad can reach queue + deeplink).
set -euo pipefail

INSTALL_BIN="${INSTALL_BIN:-/usr/local/bin/cloudflared}"
ORIGIN_URL="${TUNNEL_ORIGIN_URL:-http://127.0.0.1:80}"
STATE_DIR="${STATE_DIR:-/root/click-live/tunnel}"
LOG_FILE="${LOG_FILE:-/var/log/cloudflared-quick.log}"
ENV_FILE="${ENV_FILE:-/root/click-live/server/telegram_bot/.env}"

mkdir -p "$STATE_DIR"

if [[ ! -x "$INSTALL_BIN" ]]; then
  echo "==> Install cloudflared"
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) CF_ARCH=amd64 ;;
    aarch64|arm64) CF_ARCH=arm64 ;;
    *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
  esac
  tmp="$(mktemp)"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" -o "$tmp"
  install -m 755 "$tmp" "$INSTALL_BIN"
  rm -f "$tmp"
  "$INSTALL_BIN" --version
fi

cat > "${STATE_DIR}/run-quick-tunnel.sh" <<'RUN'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_BIN="${INSTALL_BIN:-/usr/local/bin/cloudflared}"
ORIGIN_URL="${TUNNEL_ORIGIN_URL:-http://127.0.0.1:80}"
STATE_DIR="${STATE_DIR:-/root/click-live/tunnel}"
LOG_FILE="${LOG_FILE:-/var/log/cloudflared-quick.log}"
ENV_FILE="${ENV_FILE:-/root/click-live/server/telegram_bot/.env}"
URL_FILE="${STATE_DIR}/public.url"

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"

apply_url() {
  local url="$1"
  [[ -z "$url" ]] && return 0
  if [[ -f "$URL_FILE" ]] && [[ "$(cat "$URL_FILE")" == "$url" ]]; then
    return 0
  fi
  echo "$url" > "$URL_FILE"
  echo "$(date -Is) public URL: $url" >> "$LOG_FILE"
  if [[ -f "$ENV_FILE" ]]; then
    python3 - <<PY
from pathlib import Path
import re
path = Path("$ENV_FILE")
text = path.read_text(encoding="utf-8")
for key, val in [
    ("DEEPLINK_OPEN_BASE_URL", "$url"),
    ("PUBLIC_QUEUE_BASE_URL", "$url"),
]:
    if re.search(rf"^{key}=", text, re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={val}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={val}\n"
path.write_text(text, encoding="utf-8")
print(f"Updated {key}={val}")
PY
    systemctl restart click-live-queue click-live-broadcast 2>/dev/null || true
  fi
}

extract_url() {
  grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1
}

# cloudflared logs the public URL once when the tunnel is ready
"$INSTALL_BIN" tunnel --url "$ORIGIN_URL" --no-autoupdate 2>&1 | tee -a "$LOG_FILE" | while IFS= read -r line; do
  url="$(printf '%s\n' "$line" | extract_url || true)"
  if [[ -n "$url" ]]; then
    apply_url "$url"
  fi
done
RUN
chmod +x "${STATE_DIR}/run-quick-tunnel.sh"

cat > /etc/systemd/system/cloudflared-quick.service <<EOF
[Unit]
Description=Cloudflare quick tunnel (global HTTPS for click-live)
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
Environment=TUNNEL_ORIGIN_URL=${ORIGIN_URL}
Environment=STATE_DIR=${STATE_DIR}
Environment=LOG_FILE=${LOG_FILE}
Environment=ENV_FILE=${ENV_FILE}
ExecStart=${STATE_DIR}/run-quick-tunnel.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cloudflared-quick
systemctl restart cloudflared-quick

echo "Waiting for trycloudflare URL..."
for _ in $(seq 1 30); do
  if [[ -f "${STATE_DIR}/public.url" ]]; then
    break
  fi
  sleep 1
done

if [[ -f "${STATE_DIR}/public.url" ]]; then
  PUB="$(cat "${STATE_DIR}/public.url")"
  echo ""
  echo "OK Cloudflare tunnel"
  echo "  Public URL : ${PUB}"
  echo "  Queue UI   : ${PUB}/login"
  echo "  Health     : ${PUB}/health"
  echo "  Phone app  : nhập Queue URL = ${PUB}"
  curl -sS -o /dev/null -w "  curl health -> %{http_code}\n" "${PUB}/health" || true
else
  echo "Tunnel starting — check: journalctl -u cloudflared-quick -f"
  echo "Or: tail -f ${LOG_FILE} | grep trycloudflare"
fi
