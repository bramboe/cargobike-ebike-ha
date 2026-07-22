# Bosch Smart System (Kiox 300) → Home Assistant

Get the battery percentage of a **Bosch Smart System** e-bike — any bike with a
**Kiox 300** display (Smart System hub, BRC3600) — into Home Assistant. The
battery is only served over an **encrypted, bonded** BLE link, which Home
Assistant's own Bluetooth stack (local adapter or ESP proxies) cannot establish
— so this uses a small reader that bonds with the bike via BlueZ and publishes
the battery to MQTT.

The bike appears in HA as a device (named after the bike's own brand, read over
BLE) with a **Battery** sensor and a **Last updated** timestamp. The last reading
stays shown until the next one (never "unavailable").

Developed and tested on an Urban Arrow cargo bike; other Kiox 300 / Smart System
bikes should work the same way.

## Option A — Home Assistant Add-on (recommended)

For Home Assistant running on hardware with a **working Bluetooth adapter**
(e.g. HA OS on a Raspberry Pi or bare-metal mini-PC).

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add:
   `https://github.com/bramboe/cargobike-ebike-ha`
2. Install **Cargo eBike Battery**.
3. Set `bike_address` in its *Configuration* tab (find it with
   `bluetoothctl scan on` → `smart system eBike`).
4. Put the bike in **pairing mode** and **start the add-on** — it pairs
   automatically (code-free "Just Works") and reads the battery from then on.

See [`urban_arrow_battery/DOCS.md`](urban_arrow_battery/DOCS.md) for details.

## Option B — Standalone reader

For setups where Home Assistant has **no local Bluetooth** (e.g. HA OS in a VM).
Run the reader on any nearby Linux host that has Bluetooth (for example the
Proxmox/hypervisor host). See [`tools/`](tools/):

- `bosch_mqtt_reader.py` — the reader (battery → MQTT discovery).
- `bosch-bike-reader.service` — a systemd unit.
- `bosch_test_read.py` — one-shot read to verify a bonded link.
- `comodule_motion_test.py` — experiment for the COMODULE tracker's motion data.

Pair once with `bluetoothctl` (the bike uses Just Works — no code), `trust` it,
then run the reader. The on-disk bond survives reboots.

## How it works

- Connects to the Bosch hub (`smart system eBike`) over BLE using the host's
  bonded link.
- Reads characteristic `0000eb21-eaa2-11e9-81b4-2a2ae2dbcce4` (a protobuf
  telemetry snapshot) and decodes field 10 = battery %.
- Publishes battery + a timestamp to MQTT with Home Assistant discovery.

## Limitations

- The bike allows **one** BLE connection at a time — the phone app and this
  reader cannot both be connected.
- Battery only for now. The odometer, assist mode (Eco/Tour+/Auto/Turbo) and the
  COMODULE motion sensor are still being reverse-engineered.

## Support

If this project is useful to you, consider buying me a coffee ☕

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/bramboe)

## Disclaimer

This is an **unofficial, community-made** integration. It is **not affiliated
with, endorsed by, or supported by Bosch eBike Systems or Urban Arrow**. Bosch,
Kiox, Smart System and Urban Arrow are trademarks of their respective owners.
Use is **entirely at your own risk** and without any warranty.
