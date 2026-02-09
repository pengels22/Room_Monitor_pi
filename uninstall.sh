#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="room_monitor"
SERVICE_NAME="room_monitor"

SCRIPT_PATH="/usr/local/bin/Room_Monitor.py"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
CONF_DIR="/etc/${PROJECT_NAME}"
CONF_FILE="${CONF_DIR}/config.env"
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
# Kill orphan python processes (prevents 'not-found but running')
# ------------------------------------------------
echo "==> Killing orphan Room Monitor processes (if any)"
pkill -f "${SCRIPT_PATH}" 2>/dev/null || true
pkill -f "Room_Monitor.py" 2>/dev/null || true

# ------------------------------------------------
# MQTT discovery cleanup (precise, via your script)
# ------------------------------------------------
echo
echo "==> Removing Home Assistant MQTT discovery (via Room_Monitor.py --cleanup)"

if [[ -f "${SCRIPT_PATH}" ]]; then
  # Export config.env so the script has MQTT creds when run manually
  if [[ -f "${CONF_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${CONF_FILE}"
    set +a
  fi

  /usr/bin/python3 "${SCRIPT_PATH}" --cleanup || true
else
  echo "⚠ Script not found at ${SCRIPT_PATH}; skipping discovery cleanup"
fi

# ------------------------------------------------
# Remove systemd unit
# ------------------------------------------------
echo
echo "==> Removing systemd service unit"
rm -f "${SERVICE_PATH}"
systemctl daemon-reload || true
systemctl reset-failed || true

# ------------------------------------------------
# Remove installed files
# ------------------------------------------------
echo "==> Removing installed script: ${SCRIPT_PATH}"
rm -f "${SCRIPT_PATH}"

echo "==> Removing config directory: ${CONF_DIR}"
rm -rf "${CONF_DIR}"

echo "==> Removing log directory: ${LOG_DIR}"
rm -rf "${LOG_DIR}"

# ------------------------------------------------
# Final status
# ------------------------------------------------
echo
echo "✅ Room Monitor fully removed (service + process + discovery + files)"

# ------------------------------------------------
# Optional self delete
# ------------------------------------------------
read -r -p "Delete uninstall.sh itself? (y/n): " SELFDEL
SELFDEL="${SELFDEL,,}"

if [[ "${SELFDEL}" == "y" || "${SELFDEL}" == "yes" ]]; then
  echo "Removing uninstall script..."
  rm -- "$0"
fi

echo
echo "Done."
