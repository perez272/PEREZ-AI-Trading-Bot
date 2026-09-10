#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/PEREZ-AI-Trading-Bot"
cd "$ROOT"

printf '%s\n' '=== PEREZ-AI MIGRATION INVENTORY ==='
printf 'Timestamp: %s\n' "$(date --iso-8601=seconds)"
printf 'Host: %s\n' "$(hostname)"
printf 'OS: %s\n' "$(. /etc/os-release && printf '%s %s' "$NAME" "$VERSION_ID")"
printf 'Architecture: %s\n' "$(uname -m)"
printf 'Kernel: %s\n' "$(uname -r)"
printf 'Timezone: %s\n' "$(timedatectl show -p Timezone --value 2>/dev/null || date +%Z)"
printf 'RAM: %s\n' "$(free -h | awk '/^Mem:/ {print $2}')"
printf 'Disk: %s\n' "$(df -h "$ROOT" | awk 'NR==2 {print $3" used / "$4" free ("$5")"}')"
printf 'Git commit: %s\n' "$(git rev-parse HEAD)"
printf 'Git branch: %s\n' "$(git branch --show-current)"

printf '\n=== SAFETY ===\n'
PAPER="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^PAPER_MODE=//p' | tail -1 || true)"
ORDERS="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^ORDERS_ENABLED=//p' | tail -1 || true)"
printf 'PAPER_MODE=%s\n' "${PAPER:-UNKNOWN}"
printf 'ORDERS_ENABLED=%s\n' "${ORDERS:-UNKNOWN}"

printf '\n=== SERVICES ===\n'
for svc in perez-ai.service perez-telegram-updater.service perez-tier1-option-observer.service perez-dashboard.service perez-surge-trade-bridge.service; do
  printf '%-42s %s\n' "$svc" "$(systemctl is-active "$svc" 2>/dev/null || true)"
done

printf '\n=== PERSISTENT STATE ===\n'
for f in \
  data/memory/perez_ai_memory.db \
  data/memory/tier1_option_moves.sqlite3 \
  data/memory/dashboard_telemetry.sqlite3 \
  data/runtime/trading_risk_state.json \
  data/dashboard_control.json \
  data/dashboard_actions.jsonl; do
  if [[ -e "$f" ]]; then
    printf '%-55s %s bytes\n' "$f" "$(stat -c '%s' "$f")"
  else
    printf '%-55s MISSING\n' "$f"
  fi
done

printf '\n=== SYSTEMD UNIT SOURCES ===\n'
find deploy/systemd ops -maxdepth 2 -type f \( -name '*.service' -o -name '*.timer' \) -print | sort

printf '\n=== LISTENERS ===\n'
ss -lntp 2>/dev/null | sed -n '1,80p' || true

printf '\n=== SECRET LOCATIONS (names only; contents never printed) ===\n'
if [[ -d /etc/perez-ai ]]; then
  sudo find /etc/perez-ai -maxdepth 1 -type f -printf '%f\n' | sort
else
  echo '/etc/perez-ai: MISSING'
fi

printf '\n=== MIGRATION INVENTORY COMPLETE ===\n'
