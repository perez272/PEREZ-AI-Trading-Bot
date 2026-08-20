#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-$HOME/PEREZ-AI-Trading-Bot}"
UNIT="$REPO/deploy/perez-telegram-updater.service"
TARGET="/etc/systemd/system/perez-telegram-updater.service"

sudo install -m 0644 "$UNIT" "$TARGET"
sudo systemctl daemon-reload
sudo systemctl enable --now perez-telegram-updater.service
sudo systemctl --no-pager --full status perez-telegram-updater.service
