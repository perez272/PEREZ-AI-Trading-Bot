#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/PEREZ-AI-Trading-Bot"
cd "$ROOT"
FAIL=0
pass(){ printf 'PASS  %s\n' "$*"; }
warn(){ printf 'WARN  %s\n' "$*"; }
bad(){ printf 'FAIL  %s\n' "$*"; FAIL=1; }

printf '%s\n' '=== PEREZ-AI MIGRATION VERIFICATION ==='
printf 'Host=%s Arch=%s Commit=%s\n' "$(hostname)" "$(uname -m)" "$(git rev-parse HEAD)"

[[ -d venv ]] && pass 'Python venv exists' || bad 'Python venv missing'
source venv/bin/activate
python --version
python -m compileall -q src dashboard || bad 'Python compileall failed'
pass 'Python compileall'

if [[ -f requirements.txt ]]; then
  python - <<'PY'
import importlib.metadata as m
print('Installed packages:', len(list(m.distributions())))
PY
fi

for db in data/memory/perez_ai_memory.db data/memory/tier1_option_moves.sqlite3 data/memory/dashboard_telemetry.sqlite3; do
  if [[ -f "$db" ]]; then
    if [[ "$(sqlite3 "$db" 'PRAGMA integrity_check;' | tr -d '\r\n')" == 'ok' ]]; then pass "SQLite integrity: $db"; else bad "SQLite integrity: $db"; fi
  else
    warn "SQLite database not present: $db"
  fi
done

printf '\n=== SAFETY ===\n'
ENV="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null || true)"
PAPER="$(printf '%s' "$ENV" | tr ' ' '\n' | sed -n 's/^PAPER_MODE=//p' | tail -1)"
ORDERS="$(printf '%s' "$ENV" | tr ' ' '\n' | sed -n 's/^ORDERS_ENABLED=//p' | tail -1)"
[[ "$PAPER" == 'true' ]] && pass 'PAPER_MODE=true' || bad "PAPER_MODE=$PAPER"
[[ "$ORDERS" == 'false' ]] && pass 'ORDERS_ENABLED=false' || bad "ORDERS_ENABLED=$ORDERS"

printf '\n=== SERVICES (must remain stopped during migration verification) ===\n'
for svc in perez-ai.service perez-telegram-updater.service perez-tier1-option-observer.service perez-dashboard.service perez-surge-trade-bridge.service; do
  state="$(systemctl is-active "$svc" 2>/dev/null || true)"
  [[ "$state" == 'inactive' || "$state" == 'unknown' ]] && pass "$svc is $state" || warn "$svc is $state — do not run cutover yet"
done

printf '\n=== LIVE ORDER SAFETY SCAN ===\n'
if grep -RniE 'placeOrder|placeOrderFullResponse|modifyOrder|cancelOrder' src main.py 2>/dev/null; then
  bad 'Potential live-order API pattern detected'
else
  pass 'No live-order API pattern detected'
fi

printf '\n=== PUBLIC DASHBOARD BIND ===\n'
if ss -lnt 2>/dev/null | grep -Eq '127\.0\.0\.1:8787|\[::1\]:8787'; then
  pass 'Dashboard port 8787 is loopback-only'
elif ss -lnt 2>/dev/null | grep -q ':8787'; then
  bad 'Dashboard port 8787 appears publicly bound'
else
  warn 'Port 8787 is not currently listening (acceptable before service start)'
fi

printf '\n=== REQUIRED FILES ===\n'
for f in main.py requirements.txt ops/perez-surge-trade-bridge.service dashboard/server.py src/trading_risk_manager.py; do
  [[ -f "$f" ]] && pass "$f" || bad "missing $f"
done

printf '\n=== MIGRATION RESULT ===\n'
if [[ "$FAIL" -eq 0 ]]; then
  echo 'READY_FOR_SHADOW_TESTING'
else
  echo 'NOT_READY — fix failures before starting services'
fi
exit "$FAIL"
