#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="room_monitor"
SERVICE_NAME="room_monitor"

SCRIPT_PATH="/usr/local/bin/Room_Monitor.py"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
CONF_DIR="/etc/${PROJECT_NAME}"
LOG_DIR="/var/log/${PROJECT_NAME}"

echo "====================================="
echo " Room Monitor — FULL UNINSTALL"
echo "====================================="
echo

# ------------------------------------------------
# Stop + disable systemd service
# ------------------------------------------------

echo "==> Stopping systemd service (if present)"
systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true

# ------------------------------------------------
# Kill orphan python processes
# ------------------------------------------------

echo "==> Killing orphan Room Monitor processes"
pkill -f "${SCRIPT_PATH}" 2>/dev/null || true
pkill -f "Room_Monitor.py" 2>/dev/null || true

# ------------------------------------------------
# Remove systemd unit
# ------------------------------------------------

echo "==> Removing systemd service"
rm -f "${SERVICE_PATH}"
systemctl daemon-reload
systemctl reset-failed

# ------------------------------------------------
# Remove installed files
# ------------------------------------------------

echo "==> Removing installed script"
rm -f "${SCRIPT_PATH}"

echo "==> Removing config directory"
rm -rf "${CONF_DIR}"

echo "==> Removing log directory"
rm -rf "${LOG_DIR}"

# ------------------------------------------------
# MQTT discovery cleanup (best effort)
# ------------------------------------------------

echo
echo "==> Attempting MQTT discovery cleanup (best effort)"

if command -v mosquitto_pub >/dev/null 2>&1; then
  echo "Publishing retained NULL to discovery prefix..."

  # Default HA discovery prefix
  DISC_PREFIX="homeassistant"

  mosquitto_pub -r -n -t "${DISC_PREFIX}" >/dev/null 2>&1 || true

  echo "✔ MQTT cleanup attempted"
else
  echo "⚠ mosquitto_pub not installed — skipping MQTT cleanup"
  echo "If needed, clear retained topics from your MQTT broker manually."
fi

# ------------------------------------------------
# Final status
# ------------------------------------------------

echo
echo "✅ Room Monitor fully removed"

# ------------------------------------------------
# Optional self delete
# ------------------------------------------------

read -r -p "Delete uninstall.sh itself? (y/n): " SELFDEL

if [[ "${SELFDEL,,}" == "y" ]]; then
  echo "Removing uninstall script..."
  rm -- "$0"
fi

echo
echo "Done."

#--------------------------------------------------
# End of uninstall.sh
#--------------------------------------------------