#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# install.sh — interactive setup + deps + optional systemd
# Run: sudo ./install.sh
# ============================================================

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run with sudo:"
  echo "  sudo ./install.sh"
  exit 1
fi

PROJECT_NAME="shed_gpio_mqtt"
SERVICE_NAME="shed_gpio_mqtt"

CONF_DIR="/etc/${PROJECT_NAME}"
CONF_FILE="${CONF_DIR}/config.env"

LOG_DIR="/var/log/shed"

REQ_FILE="${REQ_FILE:-requirements.txt}"
SCRIPT_SOURCE="${SCRIPT_SOURCE:-shed_gpio_mqtt.py}"   # repo filename
INSTALL_PATH="/usr/local/bin/${SCRIPT_SOURCE}"        # installed filename

SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

DEFAULT_MQTT_PORT="1883"
DEFAULT_HA_PORT="8123"
DEFAULT_DISCOVERY_PREFIX="homeassistant"

# ------------------------
# Helpers
# ------------------------
prompt_text () {
  local label="$1"
  local var=""
  read -r -p "${label}: " var
  echo "${var}"
}

prompt_default () {
  local label="$1"
  local def="$2"
  local var=""
  read -r -p "${label} [${def}]: " var
  if [[ -z "${var}" ]]; then
    echo "${def}"
  else
    echo "${var}"
  fi
}

prompt_yes_no () {
  local label="$1"
  local def="$2" # y or n
  local var=""
  while true; do
    read -r -p "${label} (y/n) [${def}]: " var
    var="${var:-$def}"
    case "${var,,}" in
      y|yes) echo "y"; return 0 ;;
      n|no)  echo "n"; return 0 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

prompt_choice () {
  # prompt_choice "Title" "1" "Option 1" "2" "Option 2" ...
  local title="$1"
  shift
  echo
  echo "${title}"
  while (( "$#" )); do
    local key="$1"; local text="$2"
    echo "  ${key}) ${text}"
    shift 2
  done
  local sel=""
  while true; do
    read -r -p "Select: " sel
    if [[ -n "${sel}" ]]; then
      echo "${sel}"
      return 0
    fi
  done
}

prompt_port_with_default () {
  local label="$1"
  local default_port="$2"
  local change
  local port="${default_port}"

  change="$(prompt_yes_no "Change default ${label} port ${default_port}?" "n")"
  if [[ "${change}" == "y" ]]; then
    while true; do
      port="$(prompt_text "Enter ${label} port")"
      if [[ "${port}" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )); then
        break
      fi
      echo "Invalid port. Enter a number 1-65535."
    done
  fi

  echo "${port}"
}

prompt_secret () {
  local label="$1"
  local var=""
  read -r -s -p "${label}: " var
  echo
  echo "${var}"
}

mask_set () {
  # prints "set" or "blank" (never show secret)
  local v="$1"
  if [[ -n "${v}" ]]; then echo "set"; else echo "blank"; fi
}

restart_service_if_present () {
  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
    systemctl daemon-reload || true
    systemctl restart "${SERVICE_NAME}.service" || true
  fi
}

# ============================================================
# Mode selection
# ============================================================
MODE="$(prompt_choice "Choose mode:" \
  "1" "Full install (deps + config + install script + optional service)" \
  "2" "Reconfigure only (rewrite config, optionally restart service)")"

FULL_INSTALL="n"
case "${MODE}" in
  1) FULL_INSTALL="y" ;;
  2) FULL_INSTALL="n" ;;
  *) echo "Invalid selection"; exit 1 ;;
esac

echo "==> ${PROJECT_NAME} installer (root)"

# ============================================================
# 1) Install deps (full install only)
# ============================================================
if [[ "${FULL_INSTALL}" == "y" ]]; then
  echo "==> apt update"
  apt-get update

  echo "==> Installing OS dependencies"
  apt-get install -y \
    python3 \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-rpi.gpio \
    i2c-tools \
    libraspberrypi-bin \
    git \
    ca-certificates

  echo "==> Upgrading pip tooling"
  pip3 install --upgrade --break-system-packages pip setuptools wheel

  if [[ -f "${REQ_FILE}" ]]; then
    echo "==> Installing Python requirements: ${REQ_FILE}"
    pip3 install --break-system-packages -r "${REQ_FILE}"
  else
    echo "!! ${REQ_FILE} not found. Create requirements.txt in the repo."
  fi
else
  echo "==> Reconfigure-only: skipping apt/pip installs"
fi

# ============================================================
# 2) Interactive config
# ============================================================
echo
echo "==> Configuration (saved to ${CONF_FILE})"
echo

HA_HOST="$(prompt_default "Home Assistant IP/hostname (optional)" "")"
HA_PORT="$(prompt_port_with_default "Home Assistant" "${DEFAULT_HA_PORT}")"

MQTT_HOST="$(prompt_default "MQTT broker IP/hostname" "192.168.1.8")"
MQTT_PORT="$(prompt_port_with_default "MQTT" "${DEFAULT_MQTT_PORT}")"

MQTT_USER="$(prompt_text "MQTT username (leave blank for anonymous)")"
MQTT_PASS=""
if [[ -n "${MQTT_USER}" ]]; then
  MQTT_PASS="$(prompt_secret "MQTT password (hidden)")"
fi

HA_DISCOVERY_PREFIX="$(prompt_default "Home Assistant discovery prefix" "${DEFAULT_DISCOVERY_PREFIX}")"

echo "==> Writing config file"
mkdir -p "${CONF_DIR}"
chmod 0755 "${CONF_DIR}"

cat > "${CONF_FILE}" <<EOF
# ${PROJECT_NAME} configuration
# Generated: $(date -Is)

# Home Assistant (optional unless you add HA REST calls)
HA_HOST=${HA_HOST}
HA_PORT=${HA_PORT}

# MQTT
MQTT_HOST=${MQTT_HOST}
MQTT_PORT=${MQTT_PORT}
MQTT_USER=${MQTT_USER}
MQTT_PASS=${MQTT_PASS}

# HA discovery
HA_DISCOVERY_PREFIX=${HA_DISCOVERY_PREFIX}
EOF

chmod 0600 "${CONF_FILE}"

# ============================================================
# 3) Log dir (always)
# ============================================================
echo "==> Ensuring log dir exists: ${LOG_DIR}"
mkdir -p "${LOG_DIR}"
chmod 0755 "${LOG_DIR}"

# ============================================================
# 4) Install python script (full install only)
# ============================================================
if [[ "${FULL_INSTALL}" == "y" ]]; then
  if [[ ! -f "${SCRIPT_SOURCE}" ]]; then
    echo "ERROR: Could not find ${SCRIPT_SOURCE} in the current directory."
    echo "If your file has a different name, run like:"
    echo "  sudo SCRIPT_SOURCE=yourfile.py ./install.sh"
    exit 1
  fi

  echo "==> Installing ${SCRIPT_SOURCE} -> ${INSTALL_PATH}"
  install -m 0755 "${SCRIPT_SOURCE}" "${INSTALL_PATH}"
else
  echo "==> Reconfigure-only: skipping script install"
fi

# ============================================================
# 5) Optional systemd service
# ============================================================
DO_SERVICE="$(prompt_yes_no "Install/Update + enable systemd service now?" "y")"
if [[ "${DO_SERVICE}" == "y" ]]; then
  # service requires installed script path to exist
  if [[ ! -f "${INSTALL_PATH}" ]]; then
    echo "!! ${INSTALL_PATH} not found."
    if [[ "${FULL_INSTALL}" == "n" ]]; then
      echo "Reconfigure-only mode can't install the script. Re-run in Full install mode, or copy your script to:"
      echo "  ${INSTALL_PATH}"
      exit 1
    else
      echo "ERROR: script install failed earlier."
      exit 1
    fi
  fi

  echo "==> Writing systemd service: ${SERVICE_PATH}"
  cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=${PROJECT_NAME} (GPIO contacts + MQTT + optional OLED)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root

EnvironmentFile=${CONF_FILE}
ExecStart=/usr/bin/python3 ${INSTALL_PATH}
Restart=always
RestartSec=2

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  echo "==> Enabling + starting service"
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}.service"
  systemctl restart "${SERVICE_NAME}.service"
else
  echo "==> Skipping systemd service install/update"
fi

# ============================================================
# 6) Summary (no secrets)
# ============================================================
echo
echo "==================== SUMMARY ===================="
echo "Mode:                 $([[ "${FULL_INSTALL}" == "y" ]] && echo "Full install" || echo "Reconfigure only")"
echo "Config file:           ${CONF_FILE} (0600)"
echo "Home Assistant host:   ${HA_HOST:-"(blank)"}"
echo "Home Assistant port:   ${HA_PORT}"
echo "MQTT host:             ${MQTT_HOST}"
echo "MQTT port:             ${MQTT_PORT}"
echo "MQTT username:         ${MQTT_USER:-"(blank/anonymous)"}"
echo "MQTT password:         $(mask_set "${MQTT_PASS}")"
echo "Discovery prefix:      ${HA_DISCOVERY_PREFIX}"
echo "Installed script:      ${INSTALL_PATH} $([[ -f "${INSTALL_PATH}" ]] && echo "(present)" || echo "(missing)")"
echo "Service file:          ${SERVICE_PATH} $([[ -f "${SERVICE_PATH}" ]] && echo "(present)" || echo "(missing)")"
echo "Log dir:               ${LOG_DIR}"
echo "================================================="
echo

if [[ "${DO_SERVICE}" == "y" ]]; then
  echo "Service status:"
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
  echo
  echo "Follow logs:"
  echo "  journalctl -u ${SERVICE_NAME}.service -f"
  echo "  tail -f ${LOG_DIR}/service_log.log"
  echo "  tail -f ${LOG_DIR}/core_log.log"
else
  echo "To enable service later, re-run:"
  echo "  sudo ./install.sh"
fi

echo
echo "==> DONE"
