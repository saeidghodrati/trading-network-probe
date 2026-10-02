#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/trader/trading-bot"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root."
  exit 1
fi

if ! id trader >/dev/null 2>&1; then
  useradd -m -s /bin/bash trader
fi

mkdir -p "$APP_DIR"
cp -a "$SRC_DIR"/. "$APP_DIR"/
mkdir -p "$APP_DIR/data"
chown -R trader:trader "$APP_DIR"

python3 -m py_compile "$APP_DIR/monitor.py"
python3 -m py_compile "$APP_DIR/paper_trader.py"
python3 -m py_compile "$APP_DIR/report.py"

install -m 644 "$APP_DIR/wallex-monitor.service" /etc/systemd/system/wallex-monitor.service
install -m 644 "$APP_DIR/wallex-paper-trader.service" /etc/systemd/system/wallex-paper-trader.service
install -m 644 "$APP_DIR/wallex-paper-trader.timer" /etc/systemd/system/wallex-paper-trader.timer

systemctl daemon-reload
systemctl enable --now wallex-monitor.service
systemctl enable --now wallex-paper-trader.timer

echo
systemctl --no-pager --full status wallex-monitor.service || true
systemctl --no-pager --full status wallex-paper-trader.timer || true
echo
echo "Recovery complete."
