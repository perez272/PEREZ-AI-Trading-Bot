#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo DOMAIN=dashboard.example.com ADMIN_USER=perez bash ops/shareable-dashboard/setup.sh
# The script will securely prompt for the dashboard password.
# The Python dashboard remains bound to 127.0.0.1:8787. Nginx is the only public entrypoint.
# This script does NOT change trading/risk settings and refuses to continue if live orders are enabled.

DOMAIN="${DOMAIN:-}"
ADMIN_USER="${ADMIN_USER:-perez}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
REPO="${REPO:-/home/ubuntu/PEREZ-AI-Trading-Bot}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

if [[ $EUID -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
if [[ -z "$DOMAIN" || "$DOMAIN" == *" "* || "$DOMAIN" == *"/"* ]]; then echo "ERROR: set DOMAIN to your real DNS hostname, e.g. DOMAIN=dashboard.example.com"; exit 2; fi
if [[ -z "$ADMIN_PASSWORD" ]]; then
  read -r -s -p "Create dashboard password (14+ chars): " ADMIN_PASSWORD; echo
fi
if [[ ${#ADMIN_PASSWORD} -lt 14 ]]; then echo "ERROR: dashboard password must be at least 14 characters."; exit 3; fi

# Hard safety guard: this web layer must never be used to turn on live trading.
ENV_OUT="$(systemctl show perez-ai.service -p Environment --value 2>/dev/null || true)"
grep -qw 'PAPER_MODE=true' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed PAPER_MODE=true'; exit 10; }
grep -qw 'ORDERS_ENABLED=false' <<<"$ENV_OUT" || { echo 'ABORT: PEREZ-AI is not confirmed ORDERS_ENABLED=false'; exit 11; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx apache2-utils certbot python3-certbot-nginx

install -d -m 0750 /etc/perez-ai
printf '%s:%s\n' "$ADMIN_USER" "$(openssl passwd -6 "$ADMIN_PASSWORD")" > /etc/nginx/.htpasswd-perez-ai
unset ADMIN_PASSWORD
chmod 0640 /etc/nginx/.htpasswd-perez-ai
chown root:www-data /etc/nginx/.htpasswd-perez-ai

sed "s/__DOMAIN__/${DOMAIN//\//\\/}/g" "$REPO/ops/shareable-dashboard/nginx.conf.template" > /etc/nginx/sites-available/perez-ai-command-center
ln -sfn /etc/nginx/sites-available/perez-ai-command-center /etc/nginx/sites-enabled/perez-ai-command-center
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# Obtain a browser-trusted certificate. DNS for DOMAIN must already point to this EC2 public IP.
if [[ -n "$CERTBOT_EMAIL" ]]; then
  certbot --nginx --non-interactive --agree-tos --email "$CERTBOT_EMAIL" --redirect -d "$DOMAIN"
else
  certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email --redirect -d "$DOMAIN"
fi

# Tighten the firewall if UFW is installed/enabled: only SSH + web entrypoints.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
fi

# Verify the dashboard remains private behind nginx and the engine safety state is unchanged.
test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/)" = "200"
! ss -lntp | grep -Eq '0\.0\.0\.0:8787|\[::\]:8787' || { echo 'ABORT: dashboard port 8787 is publicly bound'; exit 20; }
HTTP_CODE="$(curl -ks -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" https://127.0.0.1/ || true)"
[[ "$HTTP_CODE" == "401" || "$HTTP_CODE" == "400" ]] || { echo "Unexpected protected endpoint status: $HTTP_CODE"; exit 21; }

systemctl is-active --quiet perez-ai.service
systemctl is-active --quiet perez-dashboard.service

echo
printf 'PEREZ-AI SHAREABLE COMMAND CENTER READY\n'
printf 'URL: https://%s\n' "$DOMAIN"
printf 'USER: %s\n' "$ADMIN_USER"
printf 'Password: the value you entered during setup\n'
printf 'Python dashboard remains private at 127.0.0.1:8787\n'
printf 'PAPER_MODE=true and ORDERS_ENABLED=false verified\n'
printf 'Next: ensure EC2 Security Group allows TCP 80/443 and does NOT allow 8787.\n'
