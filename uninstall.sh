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
# Safety: refuse to run unless root (system paths)
# ------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run with sudo:"
  echo "  sudo ./uninstall.sh"
  exit 1
fi

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
# Remove project directory (repo folder where uninstall.sh lives)
# ------------------------------------------------
echo
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Safety rails: refuse to delete dangerous directories
case "${SCRIPT_DIR}" in
  "/"|"/root"|"/home"|"/home/"*"/"|"${HOME}" )
    echo "⚠ Refusing to delete suspicious directory: ${SCRIPT_DIR}"
    echo "If you really need to delete it, move uninstall.sh into the project folder and re-run."
    ;;
  *)
    echo "==> Project directory detected:"
    echo "    ${SCRIPT_DIR}"
    echo
    read -r -p "Remove this entire directory and ALL its contents? (y/n): " DELDIR
    DELDIR="${DELDIR,,}"

    if [[ "${DELDIR}" == "y" || "${DELDIR}" == "yes" ]]; then
      echo "Removing project directory..."
      rm -rf "${SCRIPT_DIR}"
      echo "✅ Project directory removed."
      # Note: cannot reliably delete $0 after rm -rf of its parent, so we stop here.
      echo
      echo "✅ Room Monitor fully removed (service + process + discovery + files + project directory)"
      exit 0
    else
      echo "Project directory preserved."
    fi
    ;;
esac

# ------------------------------------------------
# Final status
# ------------------------------------------------
echo
echo "✅ Room Monitor removed (service + process + discovery + installed files)"
echo "   (Project directory left intact: ${SCRIPT_DIR})"

# ------------------------------------------------
# Optional self delete (only meaningful if project dir wasn't removed)
# ------------------------------------------------
read -r -p "Delete uninstall.sh itself? (y/n): " SELFDEL
SELFDEL="${SELFDEL,,}"

if [[ "${SELFDEL}" == "y" || "${SELFDEL}" == "yes" ]]; then
  echo "Removing uninstall script..."
  rm -- "$0"
fi

echo
echo "Done."
