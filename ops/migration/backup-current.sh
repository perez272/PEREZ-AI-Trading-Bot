#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/PEREZ-AI-Trading-Bot"
cd "$ROOT"

PAPER="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^PAPER_MODE=//p' | tail -1 || true)"
ORDERS="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^ORDERS_ENABLED=//p' | tail -1 || true)"
[[ "$PAPER" == "true" ]] || { echo "REFUSED: PAPER_MODE must be true (got ${PAPER:-UNKNOWN})"; exit 20; }
[[ "$ORDERS" == "false" ]] || { echo "REFUSED: ORDERS_ENABLED must be false (got ${ORDERS:-UNKNOWN})"; exit 21; }

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${HOME}/PEREZ-MIGRATION-BACKUPS/${STAMP}"
mkdir -p "$OUT/databases" "$OUT/state" "$OUT/systemd" "$OUT/secrets"
chmod 700 "$OUT" "$OUT/secrets"

printf 'PEREZ-AI migration backup: %s\n' "$STAMP" | tee "$OUT/README.txt"
printf 'source_host=%s\n' "$(hostname)" >> "$OUT/README.txt"
printf 'source_arch=%s\n' "$(uname -m)" >> "$OUT/README.txt"
printf 'source_commit=%s\n' "$(git rev-parse HEAD)" >> "$OUT/README.txt"
printf 'paper_mode=%s\n' "$PAPER" >> "$OUT/README.txt"
printf 'orders_enabled=%s\n' "$ORDERS" >> "$OUT/README.txt"

# Record exact code state without copying .git into the migration bundle.
git rev-parse HEAD > "$OUT/GIT_COMMIT.txt"
git status --short > "$OUT/GIT_STATUS.txt"
git diff --binary > "$OUT/WORKTREE.diff" || true

DBS=(
  "data/memory/perez_ai_memory.db"
  "data/memory/tier1_option_moves.sqlite3"
  "data/memory/dashboard_telemetry.sqlite3"
)
for db in "${DBS[@]}"; do
  if [[ -f "$db" ]]; then
    dest="$OUT/databases/$(basename "$db")"
    sqlite3 "$db" ".backup '$dest'"
    integrity="$(sqlite3 "$dest" 'PRAGMA integrity_check;' | tr '\n' ' ')"
    printf '%s | integrity=%s\n' "$db" "$integrity" >> "$OUT/SQLITE_INTEGRITY.txt"
  fi
done

# Persistent JSON/JSONL state only; secrets and the Python venv are excluded.
for f in \
  data/runtime/trading_risk_state.json \
  data/dashboard_control.json \
  data/dashboard_actions.jsonl; do
  if [[ -f "$f" ]]; then
    cp -a "$f" "$OUT/state/"
  fi
done

# Repository-managed service definitions are safe to carry through Git; capture them for audit.
find deploy/systemd ops -maxdepth 2 -type f \( -name '*.service' -o -name '*.timer' \) -print0 \
  | tar --null -T - -czf "$OUT/systemd/repository-units.tgz" 2>/dev/null || true

# Capture non-secret host facts. Never print secret values.
{
  echo "hostname=$(hostname)"
  echo "arch=$(uname -m)"
  echo "kernel=$(uname -r)"
  echo "timezone=$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  echo "python=$(python3 --version 2>&1 || true)"
  echo "pip=$(pip3 --version 2>&1 || true)"
  echo "disk=$(df -h "$ROOT" | awk 'NR==2 {print $3" used / "$4" free ("$5")"}')"
} > "$OUT/HOST_FACTS.txt"

# Secrets are deliberately isolated, root-readable only, and never added to Git.
if [[ -d /etc/perez-ai ]]; then
  sudo tar -czf "$OUT/secrets/etc-perez-ai.tgz" -C /etc perez-ai
  sudo chown "$USER":"$(id -gn)" "$OUT/secrets/etc-perez-ai.tgz"
  chmod 600 "$OUT/secrets/etc-perez-ai.tgz"
fi

# Hash every artifact for transfer verification.
find "$OUT" -type f ! -path '*/secrets/*' -print0 | sort -z | xargs -0 sha256sum > "$OUT/SHA256SUMS.txt"
if [[ -f "$OUT/secrets/etc-perez-ai.tgz" ]]; then sha256sum "$OUT/secrets/etc-perez-ai.tgz" >> "$OUT/SHA256SUMS.txt"; fi

chmod -R go-rwx "$OUT"
printf '\nBACKUP_READY=%s\n' "$OUT"
printf 'SOURCE_COMMIT=%s\n' "$(git rev-parse HEAD)"
printf 'PAPER_MODE=%s\nORDERS_ENABLED=%s\n' "$PAPER" "$ORDERS"
printf 'IMPORTANT: keep this bundle outside Git. Transfer it securely to the new VPS.\n'
