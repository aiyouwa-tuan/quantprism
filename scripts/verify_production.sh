#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://caotaibanzi.xyz}"

check_contains() {
  local path="$1"
  local expect="$2"
  local body
  body="$(curl -k -sS -L --max-time 30 "${BASE_URL}${path}")"
  if [[ "$body" == *"$expect"* ]]; then
    echo "[PASS] ${path} contains ${expect}"
  else
    echo "[FAIL] ${path} missing ${expect}"
    return 1
  fi
}

check_json() {
  local path="$1"
  local expect="$2"
  local body
  body="$(curl -k -sS -L --max-time 30 "${BASE_URL}${path}")"
  if [[ "$body" == *"$expect"* ]]; then
    echo "[PASS] ${path} contains ${expect}"
  else
    echo "[FAIL] ${path} missing ${expect}"
    echo "Body: ${body}"
    return 1
  fi
}

check_contains "/" "QuantPrism"
check_contains "/goals" "设定投资目标"
check_contains "/backtest" "回测实验室"
check_contains "/scan" "标的扫描"
check_contains "/risk" "风控护盾"
check_json "/healthz" "\"status\":\"ok\""
check_json "/api/regime" "\"regime\""
check_json "/api/vix" "\"price\""

echo
echo "Basic production verification finished for ${BASE_URL}"
