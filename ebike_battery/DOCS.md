# My eBike

Reads a **Bosch Smart System** eBike (Kiox display, BRC3600 hub) over Bluetooth
Low Energy and publishes it to Home Assistant via MQTT discovery. Tested on the
**Urban Arrow Family Advanced Next**; other Bosch Smart System bikes are untested
but may also work. A device appears with these entities:

- **Battery** — last measured battery percentage.
- **Odometer** — total distance ridden (km), read from the bike itself.
- **Next service in** — km remaining until the next service is due.
- **Last updated** — when that reading was taken.
- **Ride mode** — the assist mode selected on the bike (Eco / Tour / Auto /
  Turbo / Off), captured from the bike's push channel during the read. Shows
  the last known mode between rides.
- **Range Eco / Tour+ / Auto / Turbo** — the bike's estimated remaining range
  (km) per assist mode, as the eBike Flow app shows it. Recalculated by the
  bike from riding style and charge.
- **Status** — what the add-on is doing right now: searching, *"Not paired —
  put the bike in PAIRING MODE"*, *"Connected to … — reading"*, or
  *"Battery NN% read at …"*.
- **Motion** — on while the COMODULE (URBANARROW) tracker reports the bike is
  being moved, even with the eBike switched off. The add-on stays connected to
  the always-on tracker; great for anti-theft automations / an alarm. Clears
  after `motion_off_delay` seconds of stillness.
- **Alarm** — an `alarm_control_panel` (exposed to Apple HomeKit as a **Security
  System**). Arm it (away/home/night) from HomeKit or Home Assistant; sustained
  movement while armed sets it to **triggered**. Disarm to clear.
- **Awake** — on when the bike is advertising (on / in range), off otherwise.
- **Bluetooth address** — which BLE device was selected (diagnostic).

## Requirements

- Home Assistant on hardware with a **working Bluetooth adapter** (e.g. HA OS
  on a Raspberry Pi or a bare-metal mini-PC). It does **not** work if HA runs
  in a VM without a passed-through Bluetooth adapter — in that case run the
  standalone reader from `tools/` on a Linux host instead.
- The **Mosquitto broker** add-on (or set the `mqtt_*` options manually).
- The bike's BLE address (the hub advertises as `smart system eBike`).

## Why not a normal (HACS) integration?

The Bosch hub only serves its telemetry over an **encrypted, bonded** BLE link.
Home Assistant's Bluetooth stack (local adapter or ESP proxies) cannot create
that bond, so a regular integration cannot read it. This add-on uses the host's
BlueZ stack directly, which can bond and read.

## Setup

1. Put the bike in **pairing mode** (display → connect a new device) and
   **start the add-on**. By default `bike_address` is empty, so the add-on
   **auto-detects** the hub by its name (`smart system eBike`), pairs it
   automatically (code-free "Just Works" pairing) and trusts the bond — you
   only do this once.
2. After that, whenever the bike is on and in range, the battery is read and
   updated in Home Assistant. The last reading stays shown until the next one
   (it never goes "unavailable").

The selected device's BLE address is published as a diagnostic sensor
**Bluetooth address**, so you can see which bike was picked. If more than one
"smart system eBike" is in range (e.g. a neighbour), the add-on log lists each
candidate with its signal strength — set **bike_address** to the right one to
pin it.

## Sensors & anti-theft

The **Settings → Sensoren** card is a single, unified list of every source that can
report movement or theft. Each row is enabled/disabled individually and shares the
same options:

- **Built-in sources** (pre-filled): *Tracker motion* (Bluetooth motion frames from
  the COMODULE tracker) and *Tracker presence* (trips when the bike leaves BLE
  range). Disabling *Tracker motion* also lets the add-on stop holding the BLE
  connection while armed, which **saves the module battery**.
- **External sensors**: add any number of your own Home Assistant `binary_sensor`s
  (contact, vibration, motion…) that you mount on the bike. Fully independent of
  Bluetooth.

Per-sensor options:

| Option | Meaning |
|---|---|
| **Role** | *Alarm* trips the alarm; *Motion only* shows on the dashboard but never trips. |
| **Silent / Full alarm** | Which armed modes the sensor is active in. |
| **Always on** | Triggers even when the alarm is disarmed (e.g. a tamper/vibration sensor). |
| **Unavailable = tamper** (external) | An `unavailable` entity counts as active — catches a yanked-off or dead sensor. |
| **Invert** (external) | Flip the on/off logic for sensors that report the opposite. |
| **Double-check** (external) | The alarm only trips when **two** double-check sensors confirm together within the shared window — a backup-sensor / false-alarm guard. |

Global **entry delay** (grace before a trip actually fires — time to disarm) and
**exit delay** (ignore trips right after arming — time to ride away) apply to all
sensors.

> Power user (route B): the motion, presence and alarm entities are published over
> MQTT, so you can instead point [Alarmo](https://github.com/nielsfaber/alarmo) at
> them and use its full alarm panel (user codes, areas, notification actions).

## Options

| Option | Description |
|---|---|
| `bike_address` | BLE address of the Bosch hub, e.g. `A4:0D:BC:8A:41:D7` |
| `cooldown` | Minimum seconds between reads while parked (default 120) |
| `mqtt_host` / `mqtt_port` / `mqtt_user` / `mqtt_pass` | Optional MQTT override. Leave empty to use the Mosquitto add-on automatically. |

## Notes

- The bike allows **one** BLE connection at a time. If the eBike Flow / Urban
  Arrow phone app is connected, the add-on cannot read until the phone
  disconnects (e.g. you walk away with the phone).
- The bond survives reboots; no re-pairing needed unless the bike is fully
  power-cycled at the battery.

## Disclaimer

This is an **unofficial, community-made** integration. It is **not affiliated
with, endorsed by, or supported by Bosch eBike Systems or Urban Arrow**. Bosch,
Kiox, Smart System and Urban Arrow are trademarks of their respective owners.
Use is **entirely at your own risk** and without any warranty — the author is
not liable for any damage to your bike, battery, tracker, or data.
