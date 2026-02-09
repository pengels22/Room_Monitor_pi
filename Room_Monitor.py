#!/usr/bin/env python3

# ============================================================
# Standard libs
# ============================================================
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Tuple, Any

# ============================================================
# Hardware / libs
# ============================================================
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt

# ============================================================
# MQTT / HA DISCOVERY CONFIG
# ============================================================
def _load_dotenv(path: str) -> None:
    # tiny dotenv loader (no extra dependency)
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except Exception:
        pass

# Try a few common locations (installer uses EnvironmentFile, so this is best-effort only)
_load_dotenv(".env")
_load_dotenv(os.path.join(os.path.expanduser("~"), "room_monitor", "config", "config.env"))

MQTT_HOST = os.getenv("MQTT_HOST", "192.168.1.8")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")  # blank = anonymous
MQTT_PASS = os.getenv("MQTT_PASS", "")  # blank = anonymous
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")

# ============================================================
# HOSTNAME -> DEVICE ID (automatic)
# ============================================================
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "monitor"

HOST = slugify(socket.gethostname())      # e.g. "monitor1"
DEVICE_ID = HOST                          # discovery identifiers + mqtt client id
DEVICE_NAME = HOST                        # shown as device name in HA

# ============================================================
# CONTACT CONFIG
# ============================================================
BOUNCE_MS = 120
POLL_INTERVAL_SEC = 0.05  # main loop tick

# IMPORTANT: keep your pin mapping exactly as-is
SENSORS: Dict[str, Dict[str, Any]] = {
    "zone1":  {"name": "Zone 1",  "pin": 22, "device_class": "opening"},
    "zone2":  {"name": "Zone 2",  "pin": 25, "device_class": "opening"},
    "zone3":  {"name": "Zone 3",  "pin": 5,  "device_class": "opening"},
    "zone4":  {"name": "Zone 4",  "pin": 6,  "device_class": "opening"},
    "zone5":  {"name": "Zone 5",  "pin": 12, "device_class": "opening"},
    "zone6":  {"name": "Zone 6",  "pin": 13, "device_class": "opening"},
    "zone7":  {"name": "Zone 7",  "pin": 16, "device_class": "opening"},
    "zone8":  {"name": "Zone 8",  "pin": 18, "device_class": "opening"},
    "zone9":  {"name": "Zone 9",  "pin": 17, "device_class": "opening"},
    "zone10": {"name": "Zone 10", "pin": 23, "device_class": "opening"},
}
ZONE_KEYS = list(SENSORS.keys())

# - output_toggle = normal ON/OFF switch
# - output_tap    = momentary (auto-OFF after OUTPUT_TAP_SEC)
VALID_CLASSES = ["door", "window", "opening", "output_toggle", "output_tap"]

OUTPUT_TAP_SEC = 0.5
OUTPUT_CLASSES = {"output_toggle", "output_tap"}

ICON_BY_CLASS = {
    "output_toggle": "mdi:toggle-switch",
    "output_tap":    "mdi:gesture-tap-button",
}

def is_output_class(cls: str) -> bool:
    return (cls or "").strip().lower() in OUTPUT_CLASSES

ZONE_PLACEHOLDER = "-- Select Zone --"
CLASS_PLACEHOLDER = "-- Select Class --"

ZONE_SELECT_OPTIONS = [ZONE_PLACEHOLDER] + ZONE_KEYS
CLASS_SELECT_OPTIONS = [CLASS_PLACEHOLDER] + VALID_CLASSES

# ============================================================
# Persisted config (zone classes)
# ============================================================
# Prefer /var/lib if running as systemd service; falls back to ~/.config
PERSIST_DIRS = [
    "/var/lib/room_monitor",
    "/etc/room_monitor",
    os.path.join(os.path.expanduser("~"), ".config", "room_monitor"),
]
CONFIG_PATH = None
for d in PERSIST_DIRS:
    try:
        os.makedirs(d, exist_ok=True)
        CONFIG_PATH = os.path.join(d, f"{HOST}_zones.json")
        break
    except Exception:
        continue
if CONFIG_PATH is None:
    CONFIG_PATH = os.path.join(os.path.expanduser("~"), f"{HOST}_zones.json")

def load_zone_classes() -> Dict[str, str]:
    """
    Loads {"zone1":"door",...}. Missing zones default to "opening".
    """
    try:
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        out: Dict[str, str] = {}
        for k, v in (data or {}).items():
            kk = str(k).strip()
            vv = str(v).strip().lower()
            if kk in SENSORS and vv in VALID_CLASSES:
                out[kk] = vv
        return out
    except Exception:
        return {}

def save_zone_classes(zmap: Dict[str, str]) -> None:
    try:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(zmap, f, indent=2, sort_keys=True)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass

# apply persisted classes at boot
_persisted = load_zone_classes()
for zk, cls in _persisted.items():
    SENSORS[zk]["device_class"] = cls

# ============================================================
# OLED CONFIG (OPTIONAL)
# ============================================================
OLED_ENABLED = True
OLED_I2C_PORT = 1
OLED_I2C_ADDR = 0x3C
OLED_DRIVER = "sh1106"   # "sh1106" or "ssd1306"
OLED_ROTATE = 0
OLED_UPDATE_SEC = 0.5

# ============================================================
# CPU THROTTLE MONITOR
# ============================================================
THROTTLE_MONITOR_ENABLED = True
THROTTLE_POLL_SEC = 2.0

# ============================================================
# CHROMIUM SUPERVISOR (OPTIONAL)
# ============================================================
CHROMIUM_MONITOR_ENABLED = False
CHROMIUM_SYSTEMD_UNIT = "chromium-kiosk.service"
CHROMIUM_CHECK_SEC = 5.0
CHROMIUM_ESCALATE_MAX_CRASHES = 2
CHROMIUM_ESCALATE_WINDOW_SEC = 300

# ============================================================
# LOGGING
# ============================================================
LOG_DIR = "/var/log/room_monitor"
CORE_LOG_PATH = os.path.join(LOG_DIR, "core_log.log")
SERVICE_LOG_PATH = os.path.join(LOG_DIR, "service_log.log")
CHROM_LOG_PATH = os.path.join(LOG_DIR, "chrom_log.log")

# ============================================================
# PRIORITIES (lower = higher)
# ============================================================
P_HIGH = 10
P_MEDHIGH = 30
P_MED = 60
P_LOW = 90

# ============================================================
# Runtime globals
# ============================================================
RUNNING = True

_state_lock = threading.Lock()
_contact_states = {k: False for k in SENSORS.keys()}  # True=open, False=closed
_mqtt_ok = False

_last_contact_change_key: Optional[str] = None
_last_contact_change_is_open: Optional[bool] = None

# For dropdown selections
_select_lock = threading.Lock()
_selected_zone = ZONE_PLACEHOLDER
_selected_class = CLASS_PLACEHOLDER

# ============================================================
# Loggers
# ============================================================
def make_logger(name: str, path: str, level=logging.INFO) -> logging.Logger:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        h = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5)
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        h.setFormatter(fmt)
        logger.addHandler(h)
    return logger

CORE_LOG = make_logger("core", CORE_LOG_PATH)
SVC_LOG = make_logger("service", SERVICE_LOG_PATH)
CHROM_LOG = make_logger("chrom", CHROM_LOG_PATH)

# ============================================================
# Topics / util
# ============================================================
def availability_topic() -> str:
    return f"{HOST}/availability"

# ---- INPUT (binary_sensor) topics ----
def contact_state_topic(sensor_key: str) -> str:
    return f"{HOST}_{sensor_key}/state"

def contact_discovery_topic(sensor_key: str) -> str:
    return f"{HA_DISCOVERY_PREFIX}/binary_sensor/{HOST}/{sensor_key}/config"

# ---- OUTPUT (switch) topics ----
def switch_state_topic(sensor_key: str) -> str:
    return f"{HOST}_{sensor_key}/switch/state"

def switch_command_topic(sensor_key: str) -> str:
    return f"{HOST}_{sensor_key}/switch/set"

def switch_discovery_topic(sensor_key: str) -> str:
    return f"{HA_DISCOVERY_PREFIX}/switch/{HOST}/{sensor_key}/config"

# ---- MQTT Select entities (dropdowns) ----
TOP_ZONE_SET = f"{HOST}/zone_select/set"
TOP_CLASS_SET = f"{HOST}/class_select/set"
TOP_ZONE_STATE = f"{HOST}/zone_select/state"
TOP_CLASS_STATE = f"{HOST}/class_select/state"

def zone_select_discovery_topic() -> str:
    return f"{HA_DISCOVERY_PREFIX}/select/{HOST}/zone_select/config"

def class_select_discovery_topic() -> str:
    return f"{HA_DISCOVERY_PREFIX}/select/{HOST}/class_select/config"

def _get_ip_best_effort() -> str:
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True).strip()
        if out:
            return out.split()[0]
    except Exception:
        pass
    return "n/a"

def _fingerprint(priority: int, message: str, meta: Optional[dict]) -> Tuple[Any, ...]:
    return (priority, message, json.dumps(meta, sort_keys=True) if meta is not None else None)

def get_open_keys_ordered() -> list[str]:
    # only input-type zones contribute to "open" aggregation
    with _state_lock:
        keys: list[str] = []
        for k, meta in SENSORS.items():
            if is_output_class(meta.get("device_class", "")):
                continue
            if _contact_states.get(k, False):
                keys.append(k)
        return keys

# ============================================================
# ErrorBus (priority stack + log-on-change)
# ============================================================
@dataclass
class ErrorItem:
    key: str
    message: str
    priority: int
    since: datetime
    last_update: datetime
    count: int = 1
    meta: Optional[dict] = None

class ErrorBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._errors: Dict[str, ErrorItem] = {}
        self._dirty = True
        self._last_logged_fp: Dict[str, Tuple[Any, ...]] = {}

    def _route_logger(self, key: str) -> logging.Logger:
        if key.startswith("CPU_") or key.startswith("THROTTLE") or key == "CPU_THROTTLE":
            return CORE_LOG
        if key.startswith("CHROM") or key.startswith("CHROMIUM"):
            return CHROM_LOG
        return SVC_LOG

    def raise_error(self, key: str, message: str, priority: int, meta: Optional[dict] = None, kind: str = "error"):
        now = datetime.now()
        fp = _fingerprint(priority, message, meta)
        logger = self._route_logger(key)

        with self._lock:
            existed = key in self._errors
            if existed:
                e = self._errors[key]
                e.message = message
                e.priority = priority
                e.last_update = now
                e.count += 1
                if meta is not None:
                    e.meta = meta
            else:
                self._errors[key] = ErrorItem(
                    key=key, message=message, priority=priority,
                    since=now, last_update=now, count=1, meta=meta
                )
            self._dirty = True

            prev_fp = self._last_logged_fp.get(key)
            if (not existed) or (prev_fp != fp):
                logger.info(f"[{kind.upper()}] {key} prio={priority} msg={message}")
                self._last_logged_fp[key] = fp

    def clear_error(self, key: str, kind: str = "error"):
        logger = self._route_logger(key)
        with self._lock:
            if key in self._errors:
                e = self._errors[key]
                del self._errors[key]
                self._dirty = True
                logger.info(f"[{kind.upper()}-CLEAR] {key} resolved (was prio={e.priority} msg={e.message})")
                self._last_logged_fp.pop(key, None)

    def snapshot_top(self) -> Tuple[Optional[ErrorItem], bool]:
        with self._lock:
            if not self._errors:
                return None, self._dirty
            top = min(self._errors.values(), key=lambda e: (e.priority, e.since))
            return top, self._dirty

    def mark_clean(self):
        with self._lock:
            self._dirty = False

ERRORS = ErrorBus()

# ============================================================
# CPU throttling snapshot
# ============================================================
def _sh(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()

def vcgencmd_snapshot() -> dict:
    snap: dict = {}
    try:
        thr_raw = _sh(["vcgencmd", "get_throttled"])
        temp = _sh(["vcgencmd", "measure_temp"])
        vcore = _sh(["vcgencmd", "measure_volts", "core"])
        arm = _sh(["vcgencmd", "measure_clock", "arm"])
        coreclk = _sh(["vcgencmd", "measure_clock", "core"])

        m = re.search(r"0x[0-9a-fA-F]+", thr_raw)
        thr_val = int(m.group(0), 16) if m else 0

        def bit(n: int) -> bool:
            return (thr_val & n) != 0

        flags_now = []
        flags_past = []
        if bit(0x1): flags_now.append("UNDERVOLT")
        if bit(0x2): flags_now.append("FREQ_CAP")
        if bit(0x4): flags_now.append("THROTTLED")
        if bit(0x8): flags_now.append("SOFT_TEMP")

        if bit(0x10000): flags_past.append("UNDERVOLT")
        if bit(0x20000): flags_past.append("FREQ_CAP")
        if bit(0x40000): flags_past.append("THROTTLED")
        if bit(0x80000): flags_past.append("SOFT_TEMP")

        snap.update({
            "throttled_raw": thr_raw,
            "throttled_val": hex(thr_val),
            "flags_now": flags_now,
            "flags_past": flags_past,
            "temp": temp,
            "vcore": vcore,
            "arm": arm,
            "coreclk": coreclk,
        })
    except Exception as e:
        snap["error"] = str(e)
    return snap

def log_throttle_snapshot(prefix: str, snap: dict):
    CORE_LOG.warning(
        f"{prefix} | now={snap.get('flags_now')} past={snap.get('flags_past')} "
        f"| {snap.get('throttled_raw')} | {snap.get('temp')} | {snap.get('vcore')} "
        f"| arm={snap.get('arm')} core={snap.get('coreclk')}"
    )

def throttle_monitor_loop():
    last_now_fp: Optional[Tuple[str, ...]] = None
    while RUNNING:
        snap = vcgencmd_snapshot()
        if "error" in snap:
            ERRORS.raise_error("CPU_THROTTLE_READ", f"vcgencmd read failed: {snap['error']}", P_MEDHIGH, kind="error")
            time.sleep(THROTTLE_POLL_SEC)
            continue
        else:
            ERRORS.clear_error("CPU_THROTTLE_READ", kind="error")

        now_flags = tuple(snap.get("flags_now") or [])
        fp = now_flags

        if fp != last_now_fp:
            if now_flags:
                short = " ".join(now_flags)
                ERRORS.raise_error(
                    "CPU_THROTTLE",
                    f"THROTTLE {short} | {snap.get('temp')} | {snap.get('vcore')}",
                    P_MEDHIGH,
                    meta=snap,
                    kind="error"
                )
                log_throttle_snapshot("THROTTLE_ACTIVE", snap)
            else:
                ERRORS.clear_error("CPU_THROTTLE", kind="error")
                CORE_LOG.info(
                    f"THROTTLE_CLEAR | past={snap.get('flags_past')} | {snap.get('throttled_raw')} "
                    f"| {snap.get('temp')} | {snap.get('vcore')}"
                )
            last_now_fp = fp

        time.sleep(THROTTLE_POLL_SEC)

# ============================================================
# OLED manager (error-only, fail-silent)
# ============================================================
class OledManager:
    def __init__(self):
        self.available = False
        self.device = None
        self._canvas = None
        self._font = None

    def start(self) -> None:
        if not OLED_ENABLED:
            return
        try:
            from luma.core.interface.serial import i2c
            from luma.core.render import canvas
            from PIL import ImageFont

            if OLED_DRIVER.lower() == "sh1106":
                from luma.oled.device import sh1106 as oled_dev
            else:
                from luma.oled.device import ssd1306 as oled_dev

            serial = i2c(port=OLED_I2C_PORT, address=OLED_I2C_ADDR)
            self.device = oled_dev(serial, rotate=OLED_ROTATE)
            self._canvas = canvas
            self._font = ImageFont.load_default()

            try:
                self.device.contrast(255)
                self.device.clear()
            except Exception:
                pass

            self.available = True
        except Exception:
            self.available = False
            self.device = None
            return

        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while RUNNING:
            try:
                self._draw_once()
            except Exception:
                self.available = False
                return
            time.sleep(OLED_UPDATE_SEC)

    def _clear(self) -> None:
        if not self.available or not self.device or not self._canvas:
            return
        with self._canvas(self.device):
            pass

    def _draw_once(self) -> None:
        if not self.available or not self.device or not self._canvas or not self._font:
            return

        top, dirty = ERRORS.snapshot_top()
        if not dirty:
            return

        if top is not None and top.priority >= P_LOW:
            top = None

        if top is None:
            self._clear()
            ERRORS.mark_clean()
            return

        with self._canvas(self.device) as draw:
            draw.text((0, 0), "ERROR", font=self._font, fill=255)
            draw.text((0, 14), f"{top.key}", font=self._font, fill=255)

            msg = (top.message or "")[:96]
            line1 = msg[:21]
            line2 = msg[21:42] if len(msg) > 21 else ""
            line3 = msg[42:63] if len(msg) > 42 else ""

            draw.text((0, 28), line1, font=self._font, fill=255)
            if line2:
                draw.text((0, 40), line2, font=self._font, fill=255)
            if line3:
                draw.text((0, 52), line3, font=self._font, fill=255)

        ERRORS.mark_clean()

# ============================================================
# GPIO
# ============================================================
def is_contact_open(pin: int) -> bool:
    return GPIO.input(pin) == GPIO.HIGH  # pull-up; HIGH means OPEN

def _gpio_setup_for_zone(zone_key: str) -> None:
    meta = SENSORS[zone_key]
    pin = int(meta["pin"])
    cls = meta.get("device_class", "opening")

    if is_output_class(cls):
        # Output zone default OFF
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    else:
        # Input zone pull-up
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def setup_gpio() -> None:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for key in SENSORS.keys():
        _gpio_setup_for_zone(key)

def get_output_state(zone_key: str) -> str:
    pin = int(SENSORS[zone_key]["pin"])
    return "ON" if GPIO.input(pin) == GPIO.HIGH else "OFF"

def set_output_state(zone_key: str, on: bool) -> None:
    pin = int(SENSORS[zone_key]["pin"])
    GPIO.output(pin, GPIO.HIGH if on else GPIO.LOW)

# ============================================================
# Door aggregate (low priority state)
# ============================================================
def update_door_open_state() -> None:
    open_keys = get_open_keys_ordered()
    with _state_lock:
        changed_key = _last_contact_change_key
    changed_name = SENSORS.get(changed_key, {}).get("name", "n/a") if changed_key else "n/a"

    if open_keys:
        msg = f"Doors/Windows open: {len(open_keys)} ({changed_name})"
        ERRORS.raise_error("DOOR_OPEN", msg, P_LOW, meta={"open": open_keys, "changed": changed_key}, kind="state")
    else:
        ERRORS.clear_error("DOOR_OPEN", kind="state")

# ============================================================
# MQTT helpers
# ============================================================
def _reason_code_to_int(rc) -> int:
    if rc is None:
        return 0
    v = getattr(rc, "value", None)
    if isinstance(v, int):
        return v
    if isinstance(rc, int):
        return rc
    try:
        return int(rc)
    except Exception:
        return -1

def safe_publish(client, topic: str, payload: str, qos=1, retain=True, context: str = ""):
    try:
        client.publish(topic, payload, qos=qos, retain=retain)
        ERRORS.clear_error("MQTT_PUB_FAIL", kind="error")
    except Exception as e:
        ERRORS.raise_error("MQTT_PUB_FAIL", f"MQTT publish failed: {context} {e}", P_HIGH, kind="error")

# ============================================================
# HA Discovery for entities (input=binary_sensor, output=switch)
# ============================================================
def _device_block() -> dict:
    return {
        "name": DEVICE_NAME,
        "identifiers": [DEVICE_ID],
        "manufacturer": "Raspberry Pi",
        "model": f"GPIO IO ({HOST})",
    }

def _delete_discovery(client, topic: str, why: str = "") -> None:
    # Empty retained payload deletes entity from HA discovery
    safe_publish(client, topic, "", qos=1, retain=True, context=f"delete:{why}")

def publish_entity_discovery_one(client, zone_key: str) -> None:
    avail = availability_topic()
    meta = SENSORS[zone_key]
    cls = meta.get("device_class", "opening")

    if is_output_class(cls):
        payload = {
            "name": meta["name"],
            "unique_id": f"{HOST}_{zone_key}_sw",
            "state_topic": switch_state_topic(zone_key),
            "command_topic": switch_command_topic(zone_key),
            "availability_topic": avail,
            "payload_available": "online",
            "payload_not_available": "offline",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "icon": ICON_BY_CLASS.get(cls, "mdi:toggle-switch"),
            "device": _device_block(),
        }
        safe_publish(client, switch_discovery_topic(zone_key), json.dumps(payload), qos=1, retain=True,
                     context=f"discovery:switch:{zone_key}")
    else:
        payload = {
            "name": meta["name"],
            "unique_id": f"{HOST}_{zone_key}_bin",
            "state_topic": contact_state_topic(zone_key),
            "availability_topic": avail,
            "payload_available": "online",
            "payload_not_available": "offline",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": cls,
            "device": _device_block(),
        }
        safe_publish(client, contact_discovery_topic(zone_key), json.dumps(payload), qos=1, retain=True,
                     context=f"discovery:binary:{zone_key}")

def publish_entity_discovery_all(client) -> None:
    for key in SENSORS.keys():
        publish_entity_discovery_one(client, key)

def publish_entity_state_one(client, zone_key: str) -> None:
    cls = SENSORS[zone_key].get("device_class", "opening")
    if is_output_class(cls):
        safe_publish(client, switch_state_topic(zone_key), get_output_state(zone_key), qos=1, retain=True,
                     context=f"switch_state:{zone_key}")
    else:
        publish_contact_state(client, zone_key)

# ============================================================
# Input state publish (binary sensors)
# ============================================================
def publish_contact_state(client, sensor_key: str) -> None:
    global _last_contact_change_key, _last_contact_change_is_open

    # ignore if configured as output
    if is_output_class(SENSORS[sensor_key].get("device_class", "")):
        return

    pin = int(SENSORS[sensor_key]["pin"])
    is_open = is_contact_open(pin)

    changed = False
    with _state_lock:
        prev = _contact_states.get(sensor_key, False)
        if prev != is_open:
            _contact_states[sensor_key] = is_open
            _last_contact_change_key = sensor_key
            _last_contact_change_is_open = is_open
            changed = True

    safe_publish(
        client,
        contact_state_topic(sensor_key),
        "ON" if is_open else "OFF",
        qos=1,
        retain=True,
        context=f"state:{sensor_key}"
    )

    if changed:
        SVC_LOG.info(f"SENSOR_CHANGE {sensor_key} -> {'OPEN' if is_open else 'CLOSED'}")

# ============================================================
# HA Discovery for dropdowns (MQTT Select)
# ============================================================
def publish_zone_class_select_discovery(client) -> None:
    device_block = _device_block()

    zone_payload = {
        "name": f"{HOST} Zone Select",
        "unique_id": f"{HOST}_zone_select",
        "command_topic": TOP_ZONE_SET,
        "state_topic": TOP_ZONE_STATE,
        "options": ZONE_SELECT_OPTIONS,
        "availability_topic": availability_topic(),
        "payload_available": "online",
        "payload_not_available": "offline",
        "icon": "mdi:format-list-bulleted",
        "device": device_block,
    }
    safe_publish(client, zone_select_discovery_topic(), json.dumps(zone_payload), qos=1, retain=True, context="select:zone")

    class_payload = {
        "name": f"{HOST} Class Select",
        "unique_id": f"{HOST}_class_select",
        "command_topic": TOP_CLASS_SET,
        "state_topic": TOP_CLASS_STATE,
        "options": CLASS_SELECT_OPTIONS,
        "availability_topic": availability_topic(),
        "payload_available": "online",
        "payload_not_available": "offline",
        "icon": "mdi:tag-outline",
        "device": device_block,
    }
    safe_publish(client, class_select_discovery_topic(), json.dumps(class_payload), qos=1, retain=True, context="select:class")

    global _selected_zone, _selected_class
    with _select_lock:
        _selected_zone = ZONE_PLACEHOLDER
        _selected_class = CLASS_PLACEHOLDER

    safe_publish(client, TOP_ZONE_STATE, ZONE_PLACEHOLDER, qos=1, retain=True, context="select:zone_default")
    safe_publish(client, TOP_CLASS_STATE, CLASS_PLACEHOLDER, qos=1, retain=True, context="select:class_default")

def _apply_zone_class_change(client, zone_key: str, new_class: str) -> None:
    zone_key = str(zone_key).strip()
    new_class = str(new_class).strip().lower()

    if zone_key not in SENSORS:
        SVC_LOG.warning(f"ZONE_CLASS_SET ignored: unknown zone '{zone_key}'")
        return
    if new_class not in VALID_CLASSES:
        SVC_LOG.warning(f"ZONE_CLASS_SET ignored: invalid class '{new_class}'")
        return

    old = SENSORS[zone_key].get("device_class", "opening")
    if old == new_class:
        return

    old_is_out = is_output_class(old)
    new_is_out = is_output_class(new_class)

    # 1) Persist
    SENSORS[zone_key]["device_class"] = new_class
    persisted = load_zone_classes()
    persisted[zone_key] = new_class
    save_zone_classes(persisted)

    # 2) Reconfigure GPIO mode
    try:
        _gpio_setup_for_zone(zone_key)
    except Exception as e:
        ERRORS.raise_error("GPIO_MODE", f"GPIO mode set failed: {zone_key} {e}", P_HIGH, kind="error")

    # 3) delete old discovery config so HA doesn't accumulate orphans
    if old_is_out and not new_is_out:
        _delete_discovery(client, switch_discovery_topic(zone_key), why=f"{zone_key}:switch->binary")
    if (not old_is_out) and new_is_out:
        _delete_discovery(client, contact_discovery_topic(zone_key), why=f"{zone_key}:binary->switch")

    # 4) Publish new discovery
    publish_entity_discovery_one(client, zone_key)

    # 5) Subscribe for switch command if output, and seed state
    try:
        if new_is_out:
            client.subscribe(switch_command_topic(zone_key), qos=1)
            safe_publish(client, switch_state_topic(zone_key), get_output_state(zone_key), qos=1, retain=True,
                         context=f"switch_seed:{zone_key}")
        else:
            publish_contact_state(client, zone_key)
    except Exception:
        pass

    SVC_LOG.info(f"ZONE_CLASS_SET {zone_key}: {old} -> {new_class}")

# ============================================================
# MQTT callbacks
# ============================================================
def _on_connect(client, userdata, flags, reason_code=None, properties=None):
    global _mqtt_ok
    rc = _reason_code_to_int(reason_code)
    ok = (rc == 0)
    with _state_lock:
        _mqtt_ok = ok

    if ok:
        ERRORS.clear_error("MQTT_CONNECT", kind="error")
        ERRORS.clear_error("MQTT_DOWN", kind="error")
        SVC_LOG.info("MQTT connected")
    else:
        ERRORS.raise_error("MQTT_CONNECT", f"MQTT connect rc={rc}", P_HIGH, kind="error")

def _on_disconnect(client, userdata, disconnect_flags=None, reason_code=None, properties=None):
    global _mqtt_ok
    with _state_lock:
        _mqtt_ok = False
    rc = _reason_code_to_int(reason_code)
    ERRORS.raise_error("MQTT_DOWN", f"MQTT disconnected rc={rc}", P_HIGH, kind="error")

def _on_message(client, userdata, msg):
    """
    Handles:
    - Select dropdowns (zone/class)
    - Output switch commands (per-zone)
    """
    global _selected_zone, _selected_class

    try:
        topic = (msg.topic or "").strip()
        payload = msg.payload.decode("utf-8", errors="ignore").strip()
    except Exception:
        return

    # -------- OUTPUT SWITCH COMMANDS --------
    if topic.endswith("/switch/set"):
        m = re.match(rf"^{re.escape(HOST)}_(zone\d+)/switch/set$", topic)
        if not m:
            return
        zone_key = m.group(1)
        if zone_key not in SENSORS:
            return

        cls = SENSORS[zone_key].get("device_class", "")
        if not is_output_class(cls):
            return

        cmd = payload.upper()
        if cmd not in ("ON", "OFF"):
            return

        try:
            if cls == "output_toggle":
                set_output_state(zone_key, cmd == "ON")
                safe_publish(client, switch_state_topic(zone_key), cmd, qos=1, retain=True,
                             context=f"switch_state:{zone_key}")
                SVC_LOG.info(f"OUTPUT_TOGGLE {zone_key} -> {cmd}")
                return

            # cls == "output_tap"
            if cmd == "OFF":
                set_output_state(zone_key, False)
                safe_publish(client, switch_state_topic(zone_key), "OFF", qos=1, retain=True,
                             context=f"switch_state:{zone_key}:force_off")
                SVC_LOG.info(f"OUTPUT_TAP {zone_key} -> OFF")
                return

            # cmd == "ON": pulse ON then auto-OFF
            set_output_state(zone_key, True)
            safe_publish(client, switch_state_topic(zone_key), "ON", qos=1, retain=True,
                         context=f"switch_state:{zone_key}:on")

            def _auto_off():
                try:
                    time.sleep(OUTPUT_TAP_SEC)
                    set_output_state(zone_key, False)
                    safe_publish(client, switch_state_topic(zone_key), "OFF", qos=1, retain=True,
                                 context=f"switch_state:{zone_key}:auto_off")
                except Exception as e:
                    ERRORS.raise_error("GPIO_OUT", f"tap auto-off failed: {zone_key} {e}", P_HIGH, kind="error")

            threading.Thread(target=_auto_off, daemon=True).start()
            SVC_LOG.info(f"OUTPUT_TAP {zone_key} -> PULSE {OUTPUT_TAP_SEC}s")
            return

        except Exception as e:
            ERRORS.raise_error("GPIO_OUT", f"GPIO output set failed: {zone_key} {e}", P_HIGH, kind="error")
        return

    # -------- ZONE SELECT --------
    if topic == TOP_ZONE_SET:
        z = payload

        if z == ZONE_PLACEHOLDER:
            with _select_lock:
                _selected_zone = ZONE_PLACEHOLDER
            safe_publish(client, TOP_ZONE_STATE, ZONE_PLACEHOLDER, qos=1, retain=True, context="zone_state:placeholder")
            return

        if z not in SENSORS:
            return

        with _select_lock:
            _selected_zone = z

        safe_publish(client, TOP_ZONE_STATE, ZONE_PLACEHOLDER, qos=1, retain=True, context="zone_state:bounce")
        SVC_LOG.info(f"SELECT zone -> {z} (bounced to placeholder)")
        return

    # -------- CLASS SELECT --------
    if topic == TOP_CLASS_SET:
        c = payload

        if c == CLASS_PLACEHOLDER:
            with _select_lock:
                _selected_class = CLASS_PLACEHOLDER
            safe_publish(client, TOP_CLASS_STATE, CLASS_PLACEHOLDER, qos=1, retain=True, context="class_state:placeholder")
            return

        c = c.lower()
        if c not in VALID_CLASSES:
            return

        with _select_lock:
            _selected_class = c
            z = _selected_zone

        if z in SENSORS:
            _apply_zone_class_change(client, z, c)
            SVC_LOG.info(f"SELECT class -> {c} (applied to {z})")
        else:
            SVC_LOG.info(f"SELECT class -> {c} (no zone selected; ignored)")

        safe_publish(client, TOP_CLASS_STATE, CLASS_PLACEHOLDER, qos=1, retain=True, context="class_state:bounce")
        return

def setup_mqtt():
    client = mqtt.Client(client_id=DEVICE_ID, clean_session=True)

    # Anonymous allowed: only set creds if user provided
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.will_set(availability_topic(), payload="offline", qos=1, retain=True)

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    except Exception as e:
        ERRORS.raise_error("MQTT_CONNECT", f"MQTT connect exception: {e}", P_HIGH, kind="error")
        raise

    client.loop_start()
    return client

# ============================================================
# SIGNAL HANDLING
# ============================================================
def handle_exit(signum, frame):
    global RUNNING
    RUNNING = False

# ============================================================
# MAIN
# ============================================================
def main() -> int:
    global RUNNING
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    SVC_LOG.info(f"Starting {DEVICE_ID} on host={HOST} ip={_get_ip_best_effort()} cfg={CONFIG_PATH}")

    try:
        setup_gpio()
    except Exception as e:
        ERRORS.raise_error("GPIO_INIT", f"GPIO init failed: {e}", P_HIGH, kind="error")
        SVC_LOG.exception("GPIO init failed")
        return 2

    oled = OledManager()
    oled.start()

    if THROTTLE_MONITOR_ENABLED:
        threading.Thread(target=throttle_monitor_loop, daemon=True).start()

    try:
        client = setup_mqtt()
    except Exception:
        client = None

    if client:
        safe_publish(client, availability_topic(), "online", qos=1, retain=True, context="availability:online")

        publish_zone_class_select_discovery(client)
        client.subscribe(TOP_ZONE_SET, qos=1)
        client.subscribe(TOP_CLASS_SET, qos=1)

        # Publish discovery + initial states
        publish_entity_discovery_all(client)
        for key in SENSORS.keys():
            publish_entity_state_one(client, key)

        # Subscribe switch topics for any output zones
        for key, meta in SENSORS.items():
            if is_output_class(meta.get("device_class", "")):
                client.subscribe(switch_command_topic(key), qos=1)

    # edge-detect if possible; poll fallback if not (INPUT zones only)
    polled_keys: set[str] = set()

    def make_cb(sensor_key: str):
        def _cb(channel):
            time.sleep(0.02)
            if client:
                publish_contact_state(client, sensor_key)
        return _cb

    for key, meta in SENSORS.items():
        if is_output_class(meta.get("device_class", "")):
            continue
        try:
            GPIO.add_event_detect(int(meta["pin"]), GPIO.BOTH, callback=make_cb(key), bouncetime=BOUNCE_MS)
        except RuntimeError:
            polled_keys.add(key)

    last_polled = {k: None for k in polled_keys}

    last_agg_tick = 0.0
    AGG_SEC = 1.0

    while RUNNING:
        now = time.monotonic()

        # poll any sensors that couldn't use edge detection (INPUT zones only)
        if polled_keys and client:
            for k in list(polled_keys):
                if is_output_class(SENSORS[k].get("device_class", "")):
                    # zone may have been flipped at runtime; stop polling it
                    polled_keys.discard(k)
                    continue
                pin = int(SENSORS[k]["pin"])
                v = GPIO.input(pin)
                if last_polled[k] is None or v != last_polled[k]:
                    last_polled[k] = v
                    publish_contact_state(client, k)

        # aggregate state update (logs only on changes)
        if now - last_agg_tick >= AGG_SEC:
            last_agg_tick = now
            update_door_open_state()

        time.sleep(POLL_INTERVAL_SEC)

    SVC_LOG.info("Shutting down...")

    try:
        if client:
            safe_publish(client, availability_topic(), "offline", qos=1, retain=True, context="availability:offline")
            time.sleep(0.2)
            client.loop_stop()
            client.disconnect()
    except Exception:
        pass

    try:
        GPIO.cleanup()
    except Exception:
        pass

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        SVC_LOG.exception(f"Fatal exception: {e}")
        raise
