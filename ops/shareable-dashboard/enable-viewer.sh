#!/usr/bin/env bash
set -euo pipefail

# Adds a separate read-only Viewer credential without disturbing the
# existing Certbot-managed HTTPS configuration.
DOMAIN="${DOMAIN:-15-252-68-195.nip.io}"
VIEWER_USER="${VIEWER_USER:-viewer}"
VIEWER_PASSWORD="${VIEWER_PASSWORD:-}"
ADMIN_FILE=/etc/nginx/.htpasswd-perez-ai-admin
VIEWER_FILE=/etc/nginx/.htpasswd-perez-ai-viewer
USERS_FILE=/etc/nginx/.htpasswd-perez-ai-users
CONF=/etc/nginx/sites-available/perez-ai-command-center

if [[ $EUID -ne 0 ]]; then echo 'Run with sudo.'; exit 1; fi
[[ -s "$ADMIN_FILE" ]] || { echo 'ERROR: existing admin credential file not found; do not continue.'; exit 2; }
[[ -f "$CONF" ]] || { echo 'ERROR: existing nginx config not found; do not continue.'; exit 4; }
if [[ -z "$VIEWER_PASSWORD" ]]; then VIEWER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(20))')"; fi
[[ ${#VIEWER_PASSWORD} -ge 14 ]] || { echo 'ERROR: viewer password must be at least 14 characters.'; exit 3; }

ENV_OUT="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null || true)"
grep -qw 'PAPER_MODE=true' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed PAPER_MODE=true'; exit 10; }
grep -qw 'ORDERS_ENABLED=false' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed ORDERS_ENABLED=false'; exit 11; }

printf '%s:%s\n' "$VIEWER_USER" "$(openssl passwd -6 "$VIEWER_PASSWORD")" > "$VIEWER_FILE"
cat "$ADMIN_FILE" "$VIEWER_FILE" > "$USERS_FILE"
unset VIEWER_PASSWORD
chmod 0640 "$ADMIN_FILE" "$VIEWER_FILE" "$USERS_FILE"
chown root:www-data "$ADMIN_FILE" "$VIEWER_FILE" "$USERS_FILE"

# Preserve the existing Certbot HTTPS/server configuration. Only change the
# authentication files: normal dashboard requests accept Admin + Viewer;
# the exact /api/action endpoint accepts Admin only.
cp -a "$CONF" "${CONF}.bak-viewer-$(date +%Y%m%d_%H%M%S)"
python3 - "$CONF" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
s = p.read_text()
users = '/etc/nginx/.htpasswd-perez-ai-users'
admin = '/etc/nginx/.htpasswd-perez-ai-admin'
# First make every existing dashboard auth reference use the combined users file.
s = s.replace('/etc/nginx/.htpasswd-perez-ai;', users + ';')
# Then make the exact /api/action location Admin-only.
m = re.search(r'(location\s*=\s*/api/action\s*\{)(.*?)(\n\s*\})', s, re.S)
if not m:
    raise SystemExit('ERROR: exact /api/action location was not found in nginx config')
block = m.group(0).replace(users + ';', admin + ';', 1)
s = s[:m.start()] + block + s[m.end():]
p.write_text(s)
PY

nginx -t
systemctl reload nginx

# Verify HTTPS remains enabled and protected.
CODE="$(curl -ks -o /dev/null -w '%{http_code}' "https://$DOMAIN/" || true)"
[[ "$CODE" == "401" ]] || { echo "ERROR: expected protected HTTPS status 401, got $CODE"; exit 20; }
! ss -lntp | grep -Eq '0\.0\.0\.0:8787|\[::\]:8787' || { echo 'ABORT: dashboard port 8787 is publicly bound'; exit 21; }

# Verify Viewer can read state but cannot execute an action.
# Keep the generated password in memory until both checks finish.
VIEW_CODE="$(curl -ks -u "$VIEWER_USER:$VIEWER_PASSWORD" -o /dev/null -w '%{http_code}' "https://$DOMAIN/api/state" || true)"
ADMIN_ACTION_CODE="$(curl -ks -u "$VIEWER_USER:$VIEWER_PASSWORD" -X POST -H 'Content-Type: application/json' --data '{"action":"RUN_HEALTH_AUDIT"}' -o /dev/null -w '%{http_code}' "https://$DOMAIN/api/action" || true)"
[[ "$VIEW_CODE" == "200" ]] || { echo "ERROR: viewer state access failed: HTTP $VIEW_CODE"; exit 22; }
[[ "$ADMIN_ACTION_CODE" == "401" ]] || { echo "ERROR: viewer action access is not blocked: HTTP $ADMIN_ACTION_CODE"; exit 23; }

printf '\nPEREZ-AI VIEWER ACCESS READY\n'
printf 'URL: https://%s\n' "$DOMAIN"
printf 'VIEWER USER: %s\n' "$VIEWER_USER"
printf 'VIEWER PASSWORD: %s\n' "$VIEWER_PASSWORD"
printf 'Viewer: READ-ONLY\n'
printf 'Admin: existing admin credential retained\n'
printf 'HTTPS configuration preserved\n'
printf 'Live orders remain disabled: PAPER_MODE=true / ORDERS_ENABLED=false\n'
printf 'SAVE THE VIEWER PASSWORD NOW.\n'
