#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash scripts/install_server.sh"
  exit 1
fi

APP_ROOT="${APP_ROOT:-/opt/quant/Quant}"
SERVICE_NAME="${SERVICE_NAME:-quantprism}"
DOMAIN="${DOMAIN:-caotaibanzi.xyz}"

if [[ ! -d "$APP_ROOT" ]]; then
  echo "App root not found: $APP_ROOT"
  exit 1
fi

apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

install -m 0644 "$APP_ROOT/deploy/systemd/quantprism.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sed -i "s#/opt/quant/Quant#${APP_ROOT}#g" "/etc/systemd/system/${SERVICE_NAME}.service"

install -m 0644 "$APP_ROOT/deploy/nginx/caotaibanzi.xyz.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
sed -i "s#caotaibanzi.xyz#${DOMAIN}#g" "/etc/nginx/sites-available/${DOMAIN}.conf"
sed -i "s#/opt/quant/Quant#${APP_ROOT}#g" "/etc/nginx/sites-available/${DOMAIN}.conf"

ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
rm -f /etc/nginx/sites-enabled/default

chmod +x "$APP_ROOT/scripts/run_prod.sh"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

nginx -t
systemctl reload nginx

echo
echo "Base install finished."
echo "Next, issue TLS cert:"
echo "  certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
echo
echo "Then verify:"
echo "  bash ${APP_ROOT}/scripts/verify_production.sh https://${DOMAIN}"
