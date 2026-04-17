#!/usr/bin/env bash
# Remote deployment script — runs on VPS after SCP sync
set -euo pipefail

cd /opt/quant/Quant

echo "=== Starting deploy at $(date) ==="

# Fix ownership
chown -R www-data:www-data app/ requirements.txt scripts/ 2>/dev/null || true
chmod +x scripts/run_prod.sh scripts/remote_deploy.sh

# Sync systemd service
if ! diff -q deploy/systemd/quantprism.service /etc/systemd/system/quantprism.service > /dev/null 2>&1; then
  cp deploy/systemd/quantprism.service /etc/systemd/system/quantprism.service
  systemctl daemon-reload
  echo "systemd service updated"
fi

# Sync nginx config (proxy_pass to uvicorn)
cp /etc/nginx/sites-enabled/caotaibanzi.xyz.conf /tmp/nginx_caotaibanzi.bak 2>/dev/null || true
if ! diff -q deploy/nginx/caotaibanzi.xyz.conf /etc/nginx/sites-enabled/caotaibanzi.xyz.conf > /dev/null 2>&1; then
  cp deploy/nginx/caotaibanzi.xyz.conf /etc/nginx/sites-enabled/caotaibanzi.xyz.conf
  echo "=== nginx -t ==="
  if nginx -t 2>&1; then
    systemctl reload nginx && echo "nginx config updated"
  else
    echo "nginx -t FAILED, reverting to backup"
    cp /tmp/nginx_caotaibanzi.bak /etc/nginx/sites-enabled/caotaibanzi.xyz.conf 2>/dev/null || true
  fi
else
  echo "nginx config unchanged, reloading"
  nginx -t 2>&1 && systemctl reload nginx || true
fi

# Install dependencies
venv/bin/pip install -q -r requirements.txt

# Stop service cleanly, clear port 8000, start fresh
systemctl stop quantprism || true
sleep 3
PORT_PID=$(fuser 8000/tcp 2>/dev/null | awk '{print $1}') || true
if [ -n "$PORT_PID" ]; then
  echo "Killing stale PID $PORT_PID on port 8000"
  kill -9 "$PORT_PID" 2>/dev/null || true
  sleep 1
fi
systemctl start quantprism
sleep 10

# Recent logs
echo "=== journalctl last 20 lines ==="
journalctl -u quantprism -n 20 --no-pager || true

# Internal health check
echo "=== curl localhost:8000 ==="
curl -s --max-time 5 http://127.0.0.1:8000/ -o /dev/null -w "status: %{http_code}\n" 2>&1 || echo "CURL_FAILED"

# Final check
systemctl is-active --quiet quantprism && echo "Deploy OK" || \
  (systemctl status quantprism --no-pager; journalctl -u quantprism -n 50 --no-pager; exit 1)
