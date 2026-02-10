# Room Monitor

GPIO → MQTT → Home Assistant

## Overview

Room Monitor is a Raspberry Pi service that publishes GPIO zones to MQTT
and automatically creates Home Assistant entities using MQTT Discovery.

It supports:

-   GPIO **input zones** (door/window/opening sensors)
-   GPIO **output zones** (relay control)
-   Runtime zone class switching via Home Assistant dropdowns
-   Persistent zone configuration across reboots
-   Optional OLED status display
-   Optional CPU throttle/undervoltage monitoring

Entities appear automatically in Home Assistant --- no manual YAML
required.

------------------------------------------------------------------------

## Requirements

### Hardware

-   Raspberry Pi (Raspberry Pi OS recommended)
-   GPIO sensors and/or relay drivers
-   MQTT broker
-   Home Assistant with MQTT integration enabled

### Software

-   Python 3
-   paho-mqtt
-   RPi.GPIO

Optional (OLED): - luma.oled - Pillow

------------------------------------------------------------------------

## Installation (Recommended)

Clone the repo:

``` bash
git clone https://github.com/pengels22/Room_Monitor_pi.git
cd Room_Monitor_pi
```

Run the installer:

``` bash
sudo ./install.sh
```

The installer will:

-   Install dependencies
-   Create `/etc/room_monitor/config.env`
-   Install the Python service
-   Optionally create a systemd service

------------------------------------------------------------------------

## Configuration

MQTT settings are stored in:

    /etc/room_monitor/config.env

Example:

    MQTT_HOST=192.168.1.8
    MQTT_PORT=1883
    MQTT_USER=mqtt
    MQTT_PASS=password
    HA_DISCOVERY_PREFIX=homeassistant

If username is blank, anonymous MQTT is used.

------------------------------------------------------------------------

## Running

### Systemd service (recommended)

``` bash
sudo systemctl enable room_monitor
sudo systemctl start room_monitor
```

View status:

``` bash
sudo systemctl status room_monitor
```

View logs:

``` bash
journalctl -u room_monitor -f
```

### Manual run

``` bash
python3 Room_Monitor.py
```

------------------------------------------------------------------------

## Zone Behavior

### Inputs

-   Pull-up logic
-   HIGH = open
-   LOW = closed

### Outputs

`output_toggle`\
→ Normal ON/OFF relay

`output_tap`\
→ Momentary pulse (auto-off)

Use relay drivers --- **never drive coils directly from GPIO**.

------------------------------------------------------------------------

## Home Assistant Integration

On startup, Room Monitor publishes MQTT discovery topics for:

-   Binary sensors (inputs)
-   Switches (outputs)
-   Zone/class selectors

Entities update automatically when zone classes change.

------------------------------------------------------------------------

## Cleanup / Entity Removal

To remove all MQTT discovery entities:

``` bash
sudo python3 /usr/local/bin/Room_Monitor.py --cleanup
```

This is automatically called by the uninstall script.

------------------------------------------------------------------------

## Uninstall

``` bash
sudo ./uninstall.sh
```

Removes:

-   systemd service
-   running processes
-   MQTT discovery entities
-   config and logs

------------------------------------------------------------------------

## Troubleshooting

Nothing appears in Home Assistant:

-   Verify MQTT broker connectivity
-   Check HA MQTT integration
-   Check logs:

``` bash
journalctl -u room_monitor -f
```

Relay doesn't activate:

-   Confirm GPIO wiring
-   Verify zone class is output type
-   Use proper relay driver hardware

------------------------------------------------------------------------

## Customization

Inside the script:

    OUTPUT_TAP_SEC
    OLED_ENABLED
    THROTTLE_MONITOR_ENABLED

------------------------------------------------------------------------

## Safety Notes

-   Outputs default OFF at boot
-   Use proper drivers for GPIO outputs
-   Verify wiring before switching zone types

------------------------------------------------------------------------

## License

Personal/home automation use. Modify freely.
