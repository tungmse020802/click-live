#!/usr/bin/env bash
# Install frp server on VPS (run ON the VPS as root).
set -euo pipefail

FRP_VERSION="${FRP_VERSION:-0.61.1}"
INSTALL_DIR="${INSTALL_DIR:-/opt/frp}"
FRP_PORT="${FRP_PORT:-7000}"
PHONE_REMOTE_PORT="${PHONE_REMOTE_PORT:-8791}"
ENV_FILE="${ENV_FILE:-/root/click-live/frp/frps.env}"

mkdir -p "$(dirname "$ENV_FILE")"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) FRP_ARCH=amd64 ;;
  aarch64|arm64) FRP_ARCH=arm64 ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

TARBALL="frp_${FRP_VERSION}_linux_${FRP_ARCH}.tar.gz"
URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${TARBALL}"

if [[ ! -x "${INSTALL_DIR}/frps" ]]; then
  echo "==> Download frp ${FRP_VERSION} (${FRP_ARCH})"
  tmp="$(mktemp -d)"
  curl -fsSL "$URL" -o "${tmp}/${TARBALL}"
  tar xzf "${tmp}/${TARBALL}" -C "$tmp"
  rm -rf "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  cp "${tmp}/frp_${FRP_VERSION}_linux_${FRP_ARCH}/frps" "$INSTALL_DIR/"
  cp "${tmp}/frp_${FRP_VERSION}_linux_${FRP_ARCH}/frps.toml" "${INSTALL_DIR}/frps.toml.example"
  rm -rf "$tmp"
fi

if [[ -f "$ENV_FILE" ]] && grep -q '^FRP_TOKEN=' "$ENV_FILE"; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  echo "==> Reuse existing FRP_TOKEN from $ENV_FILE"
else
  FRP_TOKEN="$(openssl rand -hex 24)"
  cat > "$ENV_FILE" <<EOF
FRP_TOKEN=${FRP_TOKEN}
FRP_PORT=${FRP_PORT}
PHONE_REMOTE_PORT=${PHONE_REMOTE_PORT}
FRP_PUBLIC_HOST=${FRP_PUBLIC_HOST:-160.30.19.215}
FRP_FREE_DOMAIN=${FRP_FREE_DOMAIN:-160-30-19-215.sslip.io}
EOF
  chmod 600 "$ENV_FILE"
  echo "==> Created $ENV_FILE"
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

cat > "${INSTALL_DIR}/frps.toml" <<EOF
bindPort = ${FRP_PORT}

auth.method = "token"
auth.token = "${FRP_TOKEN}"
EOF

cat > /etc/systemd/system/frps.service <<EOF
[Unit]
Description=frp server (phone tunnel)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/frps -c ${INSTALL_DIR}/frps.toml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable frps
systemctl restart frps

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then
  ufw allow "${FRP_PORT}/tcp" || true
  ufw allow "${PHONE_REMOTE_PORT}/tcp" || true
fi

echo ""
echo "OK frps running"
echo "  Control port : ${FRP_PORT}"
echo "  Phone relay  : 127.0.0.1:${PHONE_REMOTE_PORT} (after frpc connects)"
echo "  Free domain  : ${FRP_FREE_DOMAIN:-160-30-19-215.sslip.io}"
echo "  Token file   : ${ENV_FILE}"
systemctl is-active frps
