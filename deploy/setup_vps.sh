#!/bin/bash
# ============================================================
# Medical CAT Translator — VPS setup script
# Target: Ubuntu 24.04 LTS on Beget Cloud
# Run as root or with sudo:
#   curl -fsSL https://raw.githubusercontent.com/botirovshox-lang/med-translation/main/deploy/setup_vps.sh | bash
# Or after git clone:
#   sudo bash deploy/setup_vps.sh
# ============================================================
set -euo pipefail

REPO_URL="https://github.com/botirovshox-lang/med-translation.git"
APP_DIR="/opt/med-translation"
APP_USER="medcat"
DOMAIN=""                # filled at the end via prompt
APP_PASSWORD=""          # filled at the end via prompt

echo "════════════════════════════════════════════════════════════"
echo "  Medical CAT Translator — VPS bootstrap"
echo "════════════════════════════════════════════════════════════"

# Must be root
if [[ $EUID -ne 0 ]]; then
   echo "Run me as root: sudo bash deploy/setup_vps.sh"
   exit 1
fi

# 1. System update
echo "[1/8] Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

# 2. Base packages
echo "[2/8] Installing base packages..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl ufw \
    nginx \
    certbot python3-certbot-nginx \
    build-essential libxml2-dev libxslt-dev libjpeg-dev zlib1g-dev

# 3. Firewall
echo "[3/8] Configuring firewall..."
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow "Nginx Full"
ufw --force enable

# 4. App user
echo "[4/8] Creating app user '${APP_USER}'..."
if ! id -u ${APP_USER} >/dev/null 2>&1; then
    useradd -r -s /bin/bash -m -d /home/${APP_USER} ${APP_USER}
fi

# 5. Clone repo
echo "[5/8] Cloning repo to ${APP_DIR}..."
if [[ -d "${APP_DIR}/.git" ]]; then
    cd "${APP_DIR}" && sudo -u ${APP_USER} git pull
else
    git clone "${REPO_URL}" "${APP_DIR}"
    chown -R ${APP_USER}:${APP_USER} "${APP_DIR}"
fi

# 6. Python venv + deps
echo "[6/8] Installing Python dependencies..."
sudo -u ${APP_USER} bash -lc "
    cd ${APP_DIR}
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -q -r backend/requirements.txt
    .venv/bin/pip install -q python-docx openai google-cloud-translate anthropic || true
"

# 7. systemd unit
echo "[7/8] Installing systemd service..."
cp "${APP_DIR}/deploy/medcat.service" /etc/systemd/system/medcat.service
systemctl daemon-reload
systemctl enable medcat

# Ask for password / domain
if [[ -z "${APP_PASSWORD}" ]]; then
    read -rp "Введите пароль для входа в приложение (APP_PASSWORD): " APP_PASSWORD
fi
if [[ -z "${DOMAIN}" ]]; then
    read -rp "Введите ваш домен (например, med.yourdomain.ru): " DOMAIN
fi

# Write env file (used by systemd)
mkdir -p /etc/medcat
cat >/etc/medcat/env <<EOF
APP_PASSWORD=${APP_PASSWORD}
# Add API keys later if needed:
# OPENAI_API_KEY=sk-...
# GOOGLE_TRANSLATE_API_KEY=...
# ANTHROPIC_API_KEY=sk-ant-...
EOF
chmod 600 /etc/medcat/env

# Start service
systemctl restart medcat
sleep 2
systemctl status medcat --no-pager | head -10 || true

# 8. nginx config + SSL
echo "[8/8] Configuring nginx for ${DOMAIN}..."
sed "s/{{DOMAIN}}/${DOMAIN}/g" "${APP_DIR}/deploy/nginx.conf" > /etc/nginx/sites-available/medcat
ln -sf /etc/nginx/sites-available/medcat /etc/nginx/sites-enabled/medcat
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo
echo "Now requesting Let's Encrypt SSL for ${DOMAIN}..."
echo "(make sure the domain already points to this server's IP — A-record)"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect || \
    echo "WARN: certbot failed — run manually later: certbot --nginx -d ${DOMAIN}"

echo
echo "════════════════════════════════════════════════════════════"
echo "  Готово."
echo "  Сайт:        https://${DOMAIN}"
echo "  Логи:        journalctl -u medcat -f"
echo "  Перезапуск:  systemctl restart medcat"
echo "  Обновление:  cd ${APP_DIR} && git pull && systemctl restart medcat"
echo "════════════════════════════════════════════════════════════"
