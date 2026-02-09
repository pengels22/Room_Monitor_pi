#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# install.sh — Room Monitor installer (interactive)
# Run: sudo ./install.sh
#
# What it does (Full install):
#  - Installs OS deps (python3/pip/etc)
#  - Installs pip deps from requirements.txt
#  - Writes config to /etc/room_monitor/config.env (0600)
#  - Installs script to /usr/local/bin/Room_Monitor.py
#  - Optionally installs/enables systemd service: room_monitor.service
# ============================================================

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run with sudo:"
  echo "  sudo ./install.sh"
  exit 1
fi

PROJECT_NAME="room_monitor"
SERVICE_NAME="room_monitor"

CONF_DIR="/etc/${PROJECT_NAME}"
CONF_FILE="${CONF_DIR}/config.env"

LOG_DIR="/var/log/${PROJECT_NAME}"

REQ_FILE="${REQ_FILE:-requirements.txt}"
SCRIPT_SOURCE="${SCRIPT_SOURCE:-Room_Monitor.py}"        # repo filename
INSTALL_PATH="/usr/local/bin/${SCRIPT_SOURCE}"          # installed filename

SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

DEFAULT_MQTT_PORT="1883"
DEFAULT_HA_PORT="8123"
DEFAULT_DISCOVERY_PREFIX="homeassistant"

# ------------------------
# Helpers (robust + clear)
# ------------------------
prompt_text () {
  local label="$1"
  local example="${2:-}"
  local var=""

  if [[ -n "${example}" ]]; then
    >&2 echo -e "\n${label}\n  Example: ${example}"
  else
    >&2 echo -e "\n${label}"
  fi

  read -r -p "> " var
  echo "${var}"
}

prompt_default () {
  local label="$1"
  local def="$2"
  local example="${3:-}"
  local var=""

  if [[ -n "${example}" ]]; then
    >&2 echo -e "\n${label}\n  Default: ${def}\n  Example: ${example}"
  else
    >&2 echo -e "\n${label}\n  Default: ${def}"
  fi

  read -r -p "> " var
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
    >&2 echo -e "\n${label}\n  Enter: y or n (default: ${def})"
    read -r -p "> " var
    var="${var:-$def}"
    case "${var,,}" in
      y|yes) echo "y"; return 0 ;;
      n|no)  echo "n"; return 0 ;;
      *) >&2 echo "Please answer y or n." ;;
    esac
  done
}

prompt_choice () {
  # Print menu to stderr, echo ONLY the selected value to stdout.
  local title="$1"
  shift

  >&2 echo
  >&2 echo "${title}"
  while (( "$#" )); do
    local key="$1"; local text="$2"
    >&2 echo "  ${key}) ${text}"
    shift 2
  done

  local sel=""
  while true; do
    read -r -p "Select (enter a number): " sel
    case "${sel}" in
      1|2) echo "${sel}"; return 0 ;;
      *) >&2 echo "Invalid selection. Please enter 1 or 2." ;;
    esac
  done
}

prompt_port_with_default () {
  local label="$1"
  local default_port="$2"
  local port="${default_port}"
  local change=""

  change="$(prompt_yes_no "Change ${label} port from default ${default_port}?" "n")"
  if [[ "${change}" == "y" ]]; then
    while true; do
      port="$(prompt_text "Enter ${label} port (1–65535)" "${default_port}")"
      if [[ "${port}" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )); then
        break
      fi
      >&2 echo "Invalid port. Enter a number 1–65535."
    done
  fi

  echo "${port}"
}

prompt_secret () {
  local label="$1"
  local hint="${2:-}"
  local var=""

  >&2 echo -e "\n${label}"
  if [[ -n "${hint}" ]]; then
    >&2 echo "  ${hint}"
  fi
  read -r -s -p "> " var
  echo
  echo "${var}"
}

mask_set () {
  local v="$1"
  if [[ -n "${v}" ]]; then echo "set"; else echo "blank"; fi
}

# ============================================================
# Mode selection
# ============================================================
MODE="$(prompt_choice "Choose installer mode:" \
  "1" "Full install (apt + pip + write config + install script + optional systemd service)" \
  "2" "Reconfigure only (rewrite config; optionally restart service; NO apt/pip changes)")"

FULL_INSTALL="n"
case "${MODE}" in
  1) FULL_INSTALL="y" ;;
  2) FULL_INSTALL="n" ;;
  *) echo "Invalid selection"; exit 1 ;;
esac

echo "==> ${PROJECT_NAME} installer (root)"
echo "==> Script source:    ${SCRIPT_SOURCE}"
echo "==> Install target:   ${INSTALL_PATH}"
echo "==> Service name:     ${SERVICE_NAME}.service"
echo "==> Config file:      ${CONF_FILE}"
echo "==> Log directory:    ${LOG_DIR}"

# ============================================================
# Preflight checks (Full install)
# ============================================================
if [[ "${FULL_INSTALL}" == "y" ]]; then
  if [[ ! -f "${SCRIPT_SOURCE}" ]]; then
    echo "ERROR: Could not find ${SCRIPT_SOURCE} in $(pwd)"
    echo "Make sure you're running this from the repo root."
    echo "If the file name differs, run:"
    echo "  sudo SCRIPT_SOURCE=yourfile.py ./install.sh"
    exit 1
  fi
  if [[ ! -f "${REQ_FILE}" ]]; then
    echo "WARN: ${REQ_FILE} not found in $(pwd). pip requirements step will be skipped."
  fi
fi

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
    git \
    ca-certificates

  echo "==> Upgrading pip tooling"
  pip3 install --upgrade --break-system-packages pip setuptools || true


  if [[ -f "${REQ_FILE}" ]]; then
    echo "==> Installing Python requirements: ${REQ_FILE}"
    pip3 install --break-system-packages -r "${REQ_FILE}"
  fi
else
  echo "==> Reconfigure-only: skipping apt/pip installs"
fi

# ============================================================
# 2) Interactive config
# ============================================================
>&2 echo
>&2 echo "==> Configuration"
>&2 echo "This will write: ${CONF_FILE}"
>&2 echo " - File permissions: 0600 (root-only)"
>&2 echo " - Tip: press Enter to accept defaults."

HA_HOST="$(prompt_default "Home Assistant host (optional)" "" "homeassistant.local or 192.168.1.10")"
HA_PORT="$(prompt_port_with_default "Home Assistant" "${DEFAULT_HA_PORT}")"

MQTT_HOST="$(prompt_default "MQTT broker host/IP" "192.168.1.8" "mqtt.local or 192.168.1.8")"
MQTT_PORT="$(prompt_port_with_default "MQTT" "${DEFAULT_MQTT_PORT}")"

MQTT_USER="$(prompt_text "MQTT username (leave blank for anonymous/no-auth broker)" "mqtt")"
MQTT_PASS=""
if [[ -n "${MQTT_USER}" ]]; then
  MQTT_PASS="$(prompt_secret "MQTT password (input hidden)" "Stored in ${CONF_FILE} (0600).")"
fi

HA_DISCOVERY_PREFIX="$(prompt_default "Home Assistant discovery prefix" "${DEFAULT_DISCOVERY_PREFIX}" "homeassistant")"

echo "==> Writing config file"
mkdir -p "${CONF_DIR}"
chmod 0755 "${CONF_DIR}"

cat > "${CONF_FILE}" <<EOF
# ${PROJECT_NAME} configuration
# Generated: $(date -Is)

# Home Assistant (optional unless used by your script)
HA_HOST=${HA_HOST}
HA_PORT=${HA_PORT}

# MQTT
MQTT_HOST=${MQTT_HOST}
MQTT_PORT=${MQTT_PORT}
MQTT_USER=${MQTT_USER}
MQTT_PASS=${MQTT_PASS}

# Home Assistant discovery
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
  if [[ ! -f "${INSTALL_PATH}" ]]; then
    echo "ERROR: ${INSTALL_PATH} not found."
    if [[ "${FULL_INSTALL}" == "n" ]]; then
      echo "Reconfigure-only mode does not install the script."
      echo "Re-run in Full install mode, or manually copy your script to:"
      echo "  ${INSTALL_PATH}"
    fi
    exit 1
  fi

  echo "==> Writing systemd service: ${SERVICE_PATH}"
  cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=${PROJECT_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root

EnvironmentFile=${CONF_FILE}
ExecStart=/usr/bin/python3 ${INSTALL_PATH}
WorkingDirectory=/
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
echo "Config file:          ${CONF_FILE} (0600)"
echo "Home Assistant host:  ${HA_HOST:-"(blank)"}"
echo "Home Assistant port:  ${HA_PORT}"
echo "MQTT host:            ${MQTT_HOST}"
echo "MQTT port:            ${MQTT_PORT}"
echo "MQTT username:        ${MQTT_USER:-"(blank/anonymous)"}"
echo "MQTT password:        $(mask_set "${MQTT_PASS}")"
echo "Discovery prefix:     ${HA_DISCOVERY_PREFIX}"
echo "Installed script:     ${INSTALL_PATH} $([[ -f "${INSTALL_PATH}" ]] && echo "(present)" || echo "(missing)")"
echo "Service file:         ${SERVICE_PATH} $([[ -f "${SERVICE_PATH}" ]] && echo "(present)" || echo "(missing)")"
echo "Log dir:              ${LOG_DIR}"
echo "================================================="
echo

if [[ "${DO_SERVICE}" == "y" ]]; then
  echo "Service status:"
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
  echo
  echo "Follow logs:"
  echo "  journalctl -u ${SERVICE_NAME}.service -f"
else
  echo "To enable service later, re-run:"
  echo "  sudo ./install.sh"
fi

echo
echo "==> DONE"
