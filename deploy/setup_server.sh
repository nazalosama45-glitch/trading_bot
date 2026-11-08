#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 22.04/24.04 server. Run as root:
#   bash setup_server.sh
# Expects trading-bot.zip in the same folder (upload both files first).
set -euo pipefail

APP_USER=tradingbot
APP_DIR=/opt/trading-bot
HERE="$(cd "$(dirname "$0")" && pwd)"
ZIP="${1:-$HERE/trading-bot.zip}"

if [ "$(id -u)" -ne 0 ]; then echo "Run this as root."; exit 1; fi
if [ ! -f "$ZIP" ]; then echo "Cannot find $ZIP. Upload trading-bot.zip next to this script."; exit 1; fi

if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1800 ] && ! swapon --show | grep -q .; then
  echo "==> Small server: adding 2 GB of swap so the install doesn't run out of memory"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip unzip ufw

echo "==> Creating app user and unpacking the bot"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
unzip -oq "$ZIP" -d "$APP_DIR"
mkdir -p "$APP_DIR/logs" "$APP_DIR/data" "$APP_DIR/models"

echo "==> Installing Python packages (a few minutes)"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --no-cache-dir -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  echo
  echo "==> Binance TESTNET keys (typing is hidden; nothing is saved anywhere else)"
  read -r -s -p "Paste your testnet API key and press Enter: " API_KEY; echo
  read -r -s -p "Paste your testnet SECRET and press Enter: " API_SECRET; echo
  {
    printf 'BINANCE_API_KEY=%s\n' "$API_KEY"
    printf 'BINANCE_SECRET=%s\n' "$API_SECRET"
    cat <<'EOF'
USE_TESTNET=true
DRY_RUN=false
PRACTICE_MODE=true
SYMBOLS=BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT,XRP/USDT,ADA/USDT,DOGE/USDT,LINK/USDT,LTC/USDT,AVAX/USDT
TIMEFRAME=15m
ML_MIN_PROB=0
MAX_OPEN_POSITIONS=8
DAILY_LOSS_LIMIT_PCT=1.0
MAX_NOTIONAL_PCT=0.01
MAX_POSITION_PCT=0.02
START_CAPITAL=10000
AUTOSTART_BOT=true
EOF
  } > "$APP_DIR/.env"
  unset API_KEY API_SECRET
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> Installing the always-on service"
cat > /etc/systemd/system/trading-bot.service <<EOF
[Unit]
Description=Practice trading bot and dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python dashboard/server.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Firewall: only SSH is reachable from the internet"
ufw allow OpenSSH
ufw --force enable

systemctl daemon-reload
systemctl enable --now trading-bot
sleep 8

echo
systemctl --no-pager --lines=0 status trading-bot || true
echo
echo "Done. The bot now runs 24/7 and restarts itself after a crash or a reboot."
echo "See its log:   journalctl -u trading-bot -n 30 --no-pager"
