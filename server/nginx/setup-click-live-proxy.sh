#!/usr/bin/env bash
# Reverse proxy on port 80 so queue UI + deeplink work abroad (many networks block 8787/8792).
set -euo pipefail

DOMAIN="${CLICK_LIVE_DOMAIN:-160-30-19-215.sslip.io}"
SERVER_IP="${CLICK_LIVE_IP:-160.30.19.215}"

if ! command -v nginx >/dev/null 2>&1; then
  echo "==> Install nginx"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq nginx
fi

cat > /etc/nginx/sites-available/click-live <<EOF
# click-live: public HTTP on :80 (queue UI + deeplink API)
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${SERVER_IP} ${DOMAIN} 160.30.19.215.nip.io;

    client_max_body_size 4m;

    location ~ ^/(health|open|api/deeplink|deeplink)(/|\$) {
        proxy_pass http://127.0.0.1:8792;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/click-live /etc/nginx/sites-enabled/click-live
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "OK nginx :80"
echo "  Queue UI  : http://${DOMAIN}/login"
echo "  Deeplink  : http://${DOMAIN}/open/live?room_id=..."
echo "  Health    : http://${DOMAIN}/health"
curl -s -o /dev/null -w "local :80/login -> %{http_code}\n" "http://127.0.0.1/login" || true
