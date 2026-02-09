#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# uninstall.sh — Room Monitor removal
# Run: sudo ./uninstall.sh
#
# Removes:
#  - systemd service: room_monitor.service
#  - installed script: /usr/local/bin/Room_Monitor.py
#  - config dir: /etc/room_monitor (including config.env)
#  - log dir: /var/log/room_monitor
#
# NOTE: Does NOT remove pip-installed Python packages automatically
#       (those may be shared with other apps).
# ============================================================

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run with sudo:"
  echo "  sudo ./uninstall.sh"
  exit 1
fi

PROJECT_NAME="room_monitor"
SERVICE_NAME="room_monitor"

CONF_DIR="/etc/${PROJECT_NAME}"
LOG_DIR="/var/log/${PROJECT_NAME}"

SCRIPT_SOURCE="Room_Monitor.py"
INSTALL_PATH="/usr/local/bin/${SCRIPT_SOURCE}"

SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> Uninstalling ${PROJECT_NAME}"

# 1) Stop/disable service if it exists
if systemctl list-unit-files --type=service | grep -q "^${SERVICE_NAME}\.service"; then
  echo "==> Stopping service: ${SERVICE_NAME}.service"
  systemctl stop "${SERVICE_NAME}.service" || true

  echo "==> Disabling service: ${SERVICE_NAME}.service"
  systemctl disable "${SERVICE_NAME}.service" || true
else
  echo "==> Service not installed: ${SERVICE_NAME}.service (skipping stop/disable)"
fi

# 2) Remove service file
if [[ -f "${SERVICE_PATH}" ]]; then
  echo "==> Removing service file: ${SERVICE_PATH}"
  rm -f "${SERVICE_PATH}"
else
  echo "==> Service file not found: ${SERVICE_PATH} (skipping)"
fi

# 3) Reload systemd
echo "==> Reloading systemd"
systemctl daemon-reload || true
systemctl reset-failed || true

# 4) Remove installed script
if [[ -f "${INSTALL_PATH}" ]]; then
  echo "==> Removing installed script: ${INSTALL_PATH}"
  rm -f "${INSTALL_PATH}"
else
  echo "==> Installed script not found: ${INSTALL_PATH} (skipping)"
fi

# 5) Remove config dir
if [[ -d "${CONF_DIR}" ]]; then
  echo "==> Removing config directory: ${CONF_DIR}"
  rm -rf "${CONF_DIR}"
else
  echo "==> Config directory not found: ${CONF_DIR} (skipping)"
fi

# 6) Remove log dir
if [[ -d "${LOG_DIR}" ]]; then
  echo "==> Removing log directory: ${LOG_DIR}"
  rm -rf "${LOG_DIR}"
else
  echo "==> Log directory not found: ${LOG_DIR} (skipping)"
fi

echo
echo "==> Uninstall complete."
echo "Checks:"
echo "  systemctl list-unit-files | grep -i room_monitor || true"
echo "  ls -l /usr/local/bin/Room_Monitor.py || true"
echo "  ls -l /etc/room_monitor || true"
echo "  ls -l /var/log/room_monitor || true"
