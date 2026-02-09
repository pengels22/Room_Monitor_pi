ROOM MONITOR (GPIO → MQTT → HOME ASSISTANT)
==========================================

OVERVIEW
--------
This Raspberry Pi Python service publishes GPIO zones to MQTT and uses
Home Assistant MQTT Discovery so entities appear automatically.

It supports:
  - INPUT zones (door/window/opening) as Home Assistant binary_sensors
  - OUTPUT zones as Home Assistant switches:
      * output_toggle  = normal ON/OFF switch
      * output_tap     = momentary pulse (auto-OFF after OUTPUT_TAP_SEC)
  - Two Home Assistant “Select” dropdowns to change a zone’s class at runtime:
      * Zone Select  -> pick zone1..zone10
      * Class Select -> pick door/window/opening/output_toggle/output_tap
  - Persisting zone class changes so they survive reboot
  - Optional OLED error-only display (fail-silent if not present)
  - Optional CPU throttle/undervoltage monitor (vcgencmd snapshots + logs)

OUTPUT CLASS ICONS (CURRENT)
----------------------------
  output_toggle : mdi:toggle-switch
  output_tap    : mdi:gesture-tap-button

REQUIREMENTS
------------
Hardware:
  - Raspberry Pi running Raspberry Pi OS (or compatible)
  - GPIO wired sensors (NC/NO depending on your wiring) and/or relay drivers
  - MQTT broker reachable (Mosquitto, etc.)
  - Home Assistant with MQTT integration enabled

Software:
  - Python 3
  - RPi.GPIO
  - paho-mqtt

Optional (OLED):
  - luma.oled
  - luma.core
  - Pillow (PIL)

FILES / PATHS
-------------
Typical layout:
  /home/pi/room_monitor/room_monitor.py
  /home/pi/room_monitor/.env                    (optional)
  /home/pi/room_monitor/config/config.env       (optional)
Logs:
  /var/log/room_monitor/service_log.log
  /var/log/room_monitor/core_log.log
  /var/log/room_monitor/chrom_log.log           (only if chromium monitor enabled)

Persisted zone classes (first writable wins):
  /var/lib/room_monitor/<HOST>_zones.json
  /etc/room_monitor/<HOST>_zones.json
  /home/pi/.config/room_monitor/<HOST>_zones.json
Fallback:
  /home/pi/<HOST>_zones.json

ENVIRONMENT CONFIG
------------------
The script will load MQTT settings from (best effort):
  1) .env in the working directory
  2) ~/room_monitor/config/config.env

Supported variables:
  MQTT_HOST=192.168.1.8
  MQTT_PORT=1883
  MQTT_USER=mqtt
  MQTT_PASS=yourpassword
  HA_DISCOVERY_PREFIX=homeassistant

Notes:
  - If MQTT_USER is blank, the script connects anonymously.

INSTALL (PYTHON DEPS)
---------------------
1) System packages + pip:
    sudo apt-get update
    sudo apt-get install -y python3-pip

2) Python deps:
    pip3 install --break-system-packages paho-mqtt RPi.GPIO

Optional OLED deps:
    sudo apt-get install -y python3-pil
    pip3 install --break-system-packages luma.oled luma.core pillow

GPIO WIRING ASSUMPTIONS (INPUTS)
--------------------------------
Inputs are configured as pull-up inputs (PUD_UP).

Meaning:
  - GPIO reads HIGH  => OPEN
  - GPIO reads LOW   => CLOSED

Typical wiring for a contact:
  GPIO pin ----[contact]---- GND
  (Pi provides internal pull-up)

If your status appears reversed, your wiring (or contact type) may be inverted.

OUTPUT BEHAVIOR (RELAYS / OUTPUT PINS)
--------------------------------------
Outputs are configured as GPIO.OUT and default LOW (OFF) at boot.

Classes:
  output_toggle:
    - Command ON  => GPIO HIGH and stays HIGH until OFF
    - Command OFF => GPIO LOW

  output_tap:
    - Command ON  => GPIO HIGH for OUTPUT_TAP_SEC, then auto-LOW
    - Command OFF => immediate GPIO LOW (forced off)

Do NOT drive relay coils directly from GPIO.
Use a relay module, transistor driver, or opto-isolated board.

HOME ASSISTANT MQTT DISCOVERY DETAILS
-------------------------------------
On startup the script publishes Home Assistant discovery messages for:
  - binary_sensors for input zones (door/window/opening)
  - switches for output zones (output_toggle/output_tap)
  - 2 select entities for changing zone class

It also publishes retained state for each zone.

Discovery prefix:
  HA_DISCOVERY_PREFIX (default: homeassistant)

Binary sensor discovery topic:
  homeassistant/binary_sensor/<HOST>/<zone_key>/config

Binary sensor state topic:
  <HOST>_<zone_key>/state

Switch discovery topic:
  homeassistant/switch/<HOST>/<zone_key>/config

Switch state topic:
  <HOST>_<zone_key>/switch/state

Switch command topic:
  <HOST>_<zone_key>/switch/set

Select entities:
  <HOST> Zone Select
  <HOST> Class Select

Select command topics:
  <HOST>/zone_select/set
  <HOST>/class_select/set

Select state topics:
  <HOST>/zone_select/state
  <HOST>/class_select/state

IMPORTANT: ORPHAN PREVENTION
----------------------------
When you change a zone from input -> output or output -> input at runtime,
the script deletes the old discovery config (retained empty payload) and
publishes the new one, so Home Assistant does not accumulate orphan entities.

PERSISTED ZONE CLASS FORMAT
---------------------------
JSON file example:
  {
    "zone1": "door",
    "zone2": "window",
    "zone3": "output_toggle",
    "zone4": "output_tap"
  }

RUNNING MANUALLY
----------------
    cd ~/room_monitor
    python3 room_monitor.py

SYSTEMD SERVICE (RECOMMENDED)
-----------------------------
1) Create the service file:
    sudo nano /etc/systemd/system/room_monitor.service

2) Paste the following (edit user/path if needed):

    [Unit]
    Description=Room Monitor GPIO MQTT Service
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=pi
    WorkingDirectory=/home/pi/room_monitor
    ExecStart=/usr/bin/python3 /home/pi/room_monitor/room_monitor.py
    Restart=always
    RestartSec=2

    # Optional: if you use ~/room_monitor/config/config.env
    EnvironmentFile=-/home/pi/room_monitor/config/config.env

    [Install]
    WantedBy=multi-user.target

3) Enable and start:
    sudo systemctl daemon-reload
    sudo systemctl enable room_monitor.service
    sudo systemctl start room_monitor.service

4) Check status:
    sudo systemctl status room_monitor.service --no-pager

5) Follow logs:
    sudo journalctl -u room_monitor.service -f

TROUBLESHOOTING
---------------
1) Nothing shows up in Home Assistant
   - Verify MQTT broker is reachable from the Pi
   - Confirm Home Assistant MQTT integration is configured
   - Confirm HA discovery is enabled
   - Check logs:
       /var/log/room_monitor/service_log.log
       sudo journalctl -u room_monitor.service -f

2) Inputs show reversed open/closed
   - This script assumes pull-up logic: HIGH=open, LOW=closed
   - If you wire differently, you may need to invert logic or wiring

3) Switch toggles in HA but relay doesn’t move
   - Check GPIO pin number
   - Verify zone class is set to output_toggle or output_tap
   - Verify your relay driver hardware (do NOT drive coils directly)

4) Stale/orphan entities after changing class
   - Script deletes old discovery configs automatically
   - If HA still shows stale entities, restart HA or remove old entities manually

CUSTOMIZATION
-------------
1) Change tap pulse duration:
   OUTPUT_TAP_SEC = 0.5

2) Enable/disable OLED:
   OLED_ENABLED = True/False

3) Enable/disable throttle monitor:
   THROTTLE_MONITOR_ENABLED = True/False

SAFETY NOTES
------------
- Outputs default OFF at boot (GPIO LOW).
- Use proper drivers for outputs (relay boards, transistor drivers).
- Be careful switching a zone between input and output if the external
  circuit is not safe for both modes.

