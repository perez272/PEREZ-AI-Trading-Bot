#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/perez272/PEREZ-AI-Trading-Bot.git"
COMMIT="main"
ROOT="${HOME}/PEREZ-AI-Trading-Bot"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) COMMIT="${2:?missing commit}"; shift 2 ;;
    --repo) REPO_URL="${2:?missing repo URL}"; shift 2 ;;
    --root) ROOT="${2:?missing root}"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
done

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) echo "Architecture: ARM64 (Oracle Ampere compatible)" ;;
  x86_64) echo "Architecture: x86_64" ;;
  *) echo "WARNING: untested architecture: $ARCH" ;;
esac

[[ -r /etc/os-release ]] || { echo 'ERROR: /etc/os-release missing'; exit 10; }
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || echo "WARNING: expected Ubuntu; found ${ID:-unknown}"

# Base OS only. No trading service is started by this script.
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git python3 python3-venv python3-pip python3-dev \
  build-essential sqlite3 curl rsync nginx ca-certificates

sudo timedatectl set-timezone Asia/Kolkata || true

if [[ ! -d "$ROOT/.git" ]]; then
  mkdir -p "$(dirname "$ROOT")"
  git clone "$REPO_URL" "$ROOT"
fi
cd "$ROOT"
git fetch --all --tags --prune
if git rev-parse --verify "$COMMIT^{commit}" >/dev/null 2>&1; then
  git checkout --detach "$COMMIT"
else
  git fetch origin "$COMMIT"
  git checkout --detach "$COMMIT"
fi

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
if [[ -f requirements.txt ]]; then
  PIP_NO_CACHE_DIR=1 python -m pip install -r requirements.txt
fi

# Create expected directories without copying secrets.
mkdir -p data/memory data/runtime

# Prepare service definitions but deliberately stop/disable them until restore + verification.
if compgen -G 'deploy/systemd/*.service' >/dev/null; then
  sudo cp deploy/systemd/*.service /etc/systemd/system/ 2>/dev/null || true
fi
for f in ops/*.service; do
  [[ -f "$f" ]] || continue
  sudo cp "$f" /etc/systemd/system/
done
sudo systemctl daemon-reload

# Safety marker for the migration target. Existing service definitions also enforce paper mode.
sudo install -d -m 0755 /etc/perez-ai
sudo tee /etc/perez-ai/migration-safety.env >/dev/null <<'EOF'
PAPER_MODE=true
ORDERS_ENABLED=false
TZ=Asia/Kolkata
EOF
sudo chmod 600 /etc/perez-ai/migration-safety.env

for svc in perez-ai.service perez-telegram-updater.service perez-tier1-option-observer.service perez-dashboard.service perez-surge-trade-bridge.service; do
  sudo systemctl disable --now "$svc" 2>/dev/null || true
done

printf '\nBOOTSTRAP_READY\n'
printf 'ROOT=%s\n' "$ROOT"
printf 'COMMIT=%s\n' "$(git rev-parse HEAD)"
printf 'ARCH=%s\n' "$ARCH"
printf 'TIMEZONE=%s\n' "$(timedatectl show -p Timezone --value 2>/dev/null || true)"
printf 'SERVICES=STOPPED\n'
printf 'PAPER_MODE=true\nORDERS_ENABLED=false\n'
printf 'NEXT=transfer migration bundle, run restore.sh, then verify.sh\n'
