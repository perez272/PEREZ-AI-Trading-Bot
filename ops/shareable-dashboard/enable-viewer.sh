#!/usr/bin/env bash
set -euo pipefail

# Adds a separate read-only Viewer credential without disturbing the
# existing Certbot-managed HTTPS configuration.
DOMAIN="${DOMAIN:-15-252-68-195.nip.io}"
VIEWER_USER="${VIEWER_USER:-viewer}"
VIEWER_PASSWORD="${VIEWER_PASSWORD:-}"
LEGACY_ADMIN_FILE=/etc/nginx/.htpasswd-perez-ai
ADMIN_FILE=/etc/nginx/.htpasswd-perez-ai-admin
VIEWER_FILE=/etc/nginx/.htpasswd-perez-ai-viewer
USERS_FILE=/etc/nginx/.htpasswd-perez-ai-users
CONF=/etc/nginx/sites-available/perez-ai-command-center

if [[ $EUID -ne 0 ]]; then echo 'Run with sudo.'; exit 1; fi
[[ -f "$CONF" ]] || { echo 'ERROR: existing nginx config not found; do not continue.'; exit 4; }

# Migrate the original single-admin credential file if the new Admin file has
# not been created yet. This copies only the password hash; no plaintext
# password is exposed or changed.
if [[ ! -s "$ADMIN_FILE" ]]; then
    if [[ -s "$LEGACY_ADMIN_FILE" ]]; then
        cp -a "$LEGACY_ADMIN_FILE" "$ADMIN_FILE"
        chmod 0640 "$ADMIN_FILE"
        chown root:www-data "$ADMIN_FILE"
        echo 'Migrated existing admin credential to the new admin auth file.'
    else
        echo 'ERROR: neither the new admin credential file nor the legacy admin credential file exists.'
        exit 2
    fi
fi

if [[ -z "$VIEWER_PASSWORD" ]]; then VIEWER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(20))')"; fi
[[ ${#VIEWER_PASSWORD} -ge 14 ]] || { echo 'ERROR: viewer password must be at least 14 characters.'; exit 3; }

ENV_OUT="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null || true)"
grep -qw 'PAPER_MODE=true' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed PAPER_MODE=true'; exit 10; }
grep -qw 'ORDERS_ENABLED=false' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed ORDERS_ENABLED=false'; exit 11; }

printf '%s:%s\n' "$VIEWER_USER" "$(openssl passwd -6 "$VIEWER_PASSWORD")" > "$VIEWER_FILE"
cat "$ADMIN_FILE" "$VIEWER_FILE" > "$USERS_FILE"
chmod 0640 "$ADMIN_FILE" "$VIEWER_FILE" "$USERS_FILE"
chown root:www-data "$ADMIN_FILE" "$VIEWER_FILE" "$USERS_FILE"

# Preserve the existing Certbot HTTPS/server configuration. Existing installs
# may have only a generic location / block, so create the exact Admin-only
# /api/action location when it is missing. No certificate/server blocks are
# regenerated.
cp -a "$CONF" "${CONF}.bak-viewer-$(date +%Y%m%d_%H%M%S)"
python3 - "$CONF" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
s = p.read_text()
users = '/etc/nginx/.htpasswd-perez-ai-users'
admin = '/etc/nginx/.htpasswd-perez-ai-admin'
legacy = '/etc/nginx/.htpasswd-perez-ai'

# Convert existing dashboard authentication to the combined Admin+Viewer file.
s = s.replace(legacy + ';', users + ';')
s = s.replace(admin + ';', users + ';')

# If an exact /api/action location already exists, make it Admin-only.
m = re.search(r'(?ms)^\s*location\s*=\s*/api/action\s*\{.*?^\s*\}', s)
if m:
    block = m.group(0).replace(users + ';', admin + ';', 1)
    s = s[:m.start()] + block + s[m.end():]
else:
    # Older installs only have a generic location / block. Insert the
    # Admin-only exact-match block before it. Nginx exact locations win over /.
    marker = re.search(r'(?m)^\s*location\s+/\s*\{', s)
    if not marker:
        raise SystemExit('ERROR: generic dashboard location / was not found in nginx config')
    action = '''    # Only the Admin credential can execute dashboard control actions.\n    location = /api/action {\n        auth_basic "PEREZ-AI Admin Controls";\n        auth_basic_user_file /etc/nginx/.htpasswd-perez-ai-admin;\n        proxy_pass http://127.0.0.1:8787/api/action;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_set_header X-Remote-User $remote_user;\n        proxy_read_timeout 30s;\n    }\n\n'''
    s = s[:marker.start()] + action + s[marker.start():]

p.write_text(s)
PY

nginx -t
systemctl reload nginx

# Verify HTTPS remains enabled and protected.
CODE="$(curl -ks -o /dev/null -w '%{http_code}' "https://$DOMAIN/" || true)"
[[ "$CODE" == "401" ]] || { echo "ERROR: expected protected HTTPS status 401, got $CODE"; exit 20; }
! ss -lntp | grep -Eq '0\.0\.0\.0:8787|\[::\]:8787' || { echo 'ABORT: dashboard port 8787 is publicly bound'; exit 21; }

# Verify Viewer can read state but cannot execute an action.
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
