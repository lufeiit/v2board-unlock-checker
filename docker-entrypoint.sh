#!/usr/bin/env bash
set -euo pipefail

MODE="${MODE:-all}"
MENU="${MENU:-0}"
LIMIT="${LIMIT:-0}"
START="${START:-0}"
TIMEOUT="${TIMEOUT:-600}"
PRECHECK_TIMEOUT="${PRECHECK_TIMEOUT:-15}"
SCHEDULE_INTERVAL="${SCHEDULE_INTERVAL:-0}"

V2BOARD_PATH="${V2BOARD_PATH:-/v2board}"
V2BOARD_ENV_PATH="${V2BOARD_ENV_PATH:-}"
DB_PREFIX="${DB_PREFIX:-v2_}"
TEST_EMAIL="${TEST_EMAIL:-测试用户邮箱}"
LISTEN="${LISTEN:-127.0.0.1}"
BASE_PORT="${BASE_PORT:-21001}"
NODE_TYPES="${NODE_TYPES:-all}"
EXCLUDE_NAMES="${EXCLUDE_NAMES:-测试节点1,测试节点2}"
ADDRESS_MODE="${ADDRESS_MODE:-panel}"
NODE_DOMAIN="${NODE_DOMAIN:-}"
if [ -z "${DOMAIN_TEMPLATE:-}" ]; then
  DOMAIN_TEMPLATE='{label}.{domain}'
fi
DOMAIN_LABEL_MAP="${DOMAIN_LABEL_MAP:-}"
TLS_INSECURE="${TLS_INSECURE:-1}"

SINGBOX_CONFIG="${SINGBOX_CONFIG:-/data/singbox.json}"
PROXY_MAP="${PROXY_MAP:-/data/proxies.json}"
OUTPUT_DIR="${OUTPUT_DIR:-/data/unlock-results}"
V2BOARD_OUTPUT="${V2BOARD_OUTPUT:-}"
PUBLIC_OUTPUT="${PUBLIC_OUTPUT:-}"
FULL_V2BOARD_OUTPUT="${FULL_V2BOARD_OUTPUT:-0}"

generate_config() {
  /app/generate_anytls_singbox.py \
    --v2board "$V2BOARD_PATH" \
    ${V2BOARD_ENV_PATH:+--env-path "$V2BOARD_ENV_PATH"} \
    --table-prefix "$DB_PREFIX" \
    --email "$TEST_EMAIL" \
    --listen "$LISTEN" \
    --base-port "$BASE_PORT" \
    --output "$SINGBOX_CONFIG" \
    --map "$PROXY_MAP" \
    --types "$NODE_TYPES" \
    --exclude-names "$EXCLUDE_NAMES" \
    --address-mode "$ADDRESS_MODE" \
    --domain "$NODE_DOMAIN" \
    --domain-template "$DOMAIN_TEMPLATE" \
    ${DOMAIN_LABEL_MAP:+--domain-label-map "$DOMAIN_LABEL_MAP"} \
    ${TLS_INSECURE:+--insecure}
}

run_check() {
  /app/check_anytls_batch.py \
    --map "$PROXY_MAP" \
    --check /app/check.sh \
    --menu "$MENU" \
    --limit "$LIMIT" \
    --start "$START" \
    --timeout "$TIMEOUT" \
    --precheck-timeout "$PRECHECK_TIMEOUT" \
    --output-dir "$OUTPUT_DIR" \
    ${V2BOARD_OUTPUT:+--v2board-output "$V2BOARD_OUTPUT"} \
    ${PUBLIC_OUTPUT:+--public-output "$PUBLIC_OUTPUT"} \
    $( [ "$FULL_V2BOARD_OUTPUT" = "1" ] && printf '%s' '--full-v2board-output' )
}

run_all_once() {
  generate_config
  sing-box run -c "$SINGBOX_CONFIG" &
  pid="$!"
  trap 'kill "$pid" 2>/dev/null || true; exit 143' INT TERM
  sleep "${SINGBOX_START_WAIT:-3}"
  status=0
  run_check || status="$?"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  trap - INT TERM
  return "$status"
}

run_schedule() {
  command_name="$1"
  while true; do
    echo "schedule: starting ${command_name} at $(date '+%Y-%m-%d %H:%M:%S')"
    if "$command_name"; then
      echo "schedule: ${command_name} finished at $(date '+%Y-%m-%d %H:%M:%S')"
    else
      status="$?"
      echo "schedule: ${command_name} failed with code ${status} at $(date '+%Y-%m-%d %H:%M:%S')" >&2
      if [ "$SCHEDULE_INTERVAL" = "0" ]; then
        return "$status"
      fi
    fi

    if [ "$SCHEDULE_INTERVAL" = "0" ]; then
      break
    fi
    echo "schedule: sleeping ${SCHEDULE_INTERVAL}s"
    sleep "$SCHEDULE_INTERVAL"
  done
}

case "$MODE" in
  generate)
    run_schedule generate_config
    ;;
  singbox)
    exec sing-box run -c "$SINGBOX_CONFIG"
    ;;
  check)
    run_schedule run_check
    ;;
  all)
    run_schedule run_all_once
    ;;
  *)
    echo "Unknown MODE: $MODE" >&2
    echo "Available MODE: generate, singbox, check, all" >&2
    exit 1
    ;;
esac
