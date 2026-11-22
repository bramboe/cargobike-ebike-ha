# My eBike — Bosch Smart System → Home Assistant

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/bramboe?frequency=one-time) [![Sponsor bunq.me](https://img.shields.io/badge/Sponsor-bunq.me-2E9AD0)](https://bunq.me/bramboe)

Home Assistant add-on for Bosch Smart System bikes, developed on an Urban Arrow.
A bonded local Bluetooth connection reads the bike and publishes retained MQTT
entities. The bike can stay outside: **normal operation needs no USB cable and no
cloud account**. The bike must be awake and within Bluetooth range for a fresh
reading. Last-known readings remain visible with their timestamps.

## Features

- Existing battery, odometer, service distance, ride mode and per-mode range.
- Best-effort BLE diagnostic reads for battery health, charge cycles, voltage,
  temperature, remaining energy and component identification/firmware.
- Persistent mileage and inferred ride/measurement-interval history, including
  battery percentage-point consumption when both endpoints are usable.
- Maintenance estimate in **days, weeks and observed rides/intervals**, using up
  to 28 calendar days of mileage history, including rest days.
- Connection and receiver diagnostics, field-by-field BLE capability and age.
- Passive tracker presence, external HA sensors and an optional alarm panel.
- Optional PON location and Bosch cloud diagnostics; existing IDs are preserved.

**BLE capability differs by firmware and access level.** Rich battery fields were
observed over USB during protocol research; that does not prove they are readable
over BLE on every bike. The add-on requests only allowlisted READs and marks
DENIED/UNSUPPORTED/NO_ROUTE fields unavailable. It never imports old USB readings
as live bike data, changes bike settings or updates firmware.

## Install

1. Add `https://github.com/bramboe/cargobike-ebike-ha` under Home Assistant's
   add-on/app repositories and install **My eBike**.
2. Install/configure an MQTT broker, such as the Mosquitto add-on.
3. Open the My eBike panel, scan for the bike and select it.
4. Put the bike in pairing mode and use **Pair** in the panel.

A local Bluetooth adapter with BlueZ is needed for the encrypted bond. The
optional ESPHome proxy extends **tracker presence only**; it does not replace the
bonded local bike-data connection. Only one bike is active per add-on instance.

See [the detailed guide](ebike_battery/DOCS.md) for configuration, limitations,
history quality and suggested Home Assistant notifications.
