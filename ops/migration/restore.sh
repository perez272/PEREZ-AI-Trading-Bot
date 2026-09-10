#!/usr/bin/env bash
set -euo pipefail

BUNDLE="${1:-}"
ROOT="${HOME}/PEREZ-AI-Trading-Bot"

if [[ -z "$BUNDLE" || ! -d "$BUNDLE" ]]; then
  echo "Usage: bash ops/migration/restore.sh /path/to/PEREZ-MIGRATION-BACKUPS/<timestamp>"
  exit 2
fi
cd "$ROOT"

# Verify bundle integrity before touching persistent state.
if [[ -f "$BUNDLE/SHA256SUMS.txt" ]]; then
  (cd "$BUNDLE" && sha256sum -c SHA256SUMS.txt)
fi

mkdir -p data/memory data/runtime

# Restore SQLite backups atomically through a temporary file, then replace the destination.
restore_db() {
  local name="$1"
  local src="$BUNDLE/databases/$name"
  local dst="data/memory/$name"
  [[ -f "$src" ]] || return 0
  sqlite3 "$src" 'PRAGMA integrity_check;' | grep -qx 'ok' || { echo "REFUSED: SQLite integrity failed: $name"; exit 30; }
  local tmp="${dst}.restore.$$"
  cp -a "$src" "$tmp"
  sqlite3 "$tmp" 'PRAGMA integrity_check;' | grep -qx 'ok' || { rm -f "$tmp"; exit 31; }
  mv -f "$tmp" "$dst"
}

restore_db perez_ai_memory.db
restore_db tier1_option_moves.sqlite3
restore_db dashboard_telemetry.sqlite3

for f in "$BUNDLE/state/trading_risk_state.json" "$BUNDLE/state/dashboard_control.json" "$BUNDLE/state/dashboard_actions.jsonl"; do
  [[ -f "$f" ]] || continue
  cp -a "$f" "data/runtime/$(basename "$f")" 2>/dev/null || cp -a "$f" "data/$(basename "$f")"
done

# The dashboard control state belongs at data/dashboard_control.json, not data/runtime.
if [[ -f "$BUNDLE/state/dashboard_control.json" ]]; then
  cp -a "$BUNDLE/state/dashboard_control.json" data/dashboard_control.json
fi
if [[ -f "$BUNDLE/state/dashboard_actions.jsonl" ]]; then
  cp -a "$BUNDLE/state/dashboard_actions.jsonl" data/dashboard_actions.jsonl
fi

# Restore the private /etc/perez-ai tree only after preserving any target-side copy.
if [[ -f "$BUNDLE/secrets/etc-perez-ai.tgz" ]]; then
  sudo install -d -m 0755 /etc/perez-ai
  sudo tar -czf "/tmp/perez-ai-target-pre-restore-$(date +%Y%m%d_%H%M%S).tgz" -C /etc perez-ai 2>/dev/null || true
  sudo tar -xzf "$BUNDLE/secrets/etc-perez-ai.tgz" -C /etc
  sudo chmod 700 /etc/perez-ai
  sudo find /etc/perez-ai -type f -exec chmod 600 {} +
fi

# Refresh repo-managed units but do not start them.
if compgen -G 'deploy/systemd/*.service' >/dev/null; then
  sudo cp deploy/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
fi
for f in ops/*.service; do
  [[ -f "$f" ]] || continue
  sudo cp "$f" /etc/systemd/system/
done
sudo systemctl daemon-reload
for svc in perez-ai.service perez-telegram-updater.service perez-tier1-option-observer.service perez-dashboard.service perez-surge-trade-bridge.service; do
  sudo systemctl disable --now "$svc" 2>/dev/null || true
done

printf '\nRESTORE_COMPLETE\n'
printf 'Bundle=%s\n' "$BUNDLE"
printf 'Commit target=%s\n' "$(git rev-parse HEAD)"
printf 'Services=STOPPED\n'
printf 'Next=run bash ops/migration/verify.sh\n'
