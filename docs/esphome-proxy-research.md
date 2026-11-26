# Bosch bike data through ESPHome: research findings

Investigated 26 November 2026. This is a feasibility assessment and test plan,
not a claim that Bosch data has been read through a physical proxy.

## Conclusion

There is an existing transport implementation worth using: `bleak-esphome`
4.1.0 with `habluetooth`. A custom GATT stack is unnecessary for the first
prototype. Its declared requirements fit the add-on's Python 3.11, Bleak 3.0.2
and aioesphomeapi 46.3.0 constraints. The additional transitive dependencies and
Alpine images still need installation/build tests before inclusion.

The practical architecture choice is **who owns the Bluetooth subscription**.
The present add-on connects directly to the ESPHome API, whereas a Home Assistant
integration can reuse HA's already registered Bluetooth scanners and routing.

## Findings and their consequences

| Finding | Consequence for this project |
|---|---|
| ESPHome advertises active-connection, pairing and caching capabilities. | Check the actual device flags; a reachable API alone does not establish suitability. |
| `bleak-esphome` implements pair, read, write and notifications. | Reuse the Bosch parsing and read-session code behind a transport selection. |
| The ESPHome 2026.11.0 source has one Bluetooth API subscriber; a new subscriber replaces an existing one. | A separate add-on connection can interrupt HA's Bluetooth proxy use. Connection slots do not solve subscriber ownership. |
| Current firmware emits raw advertisements; our presence loop subscribes to the legacy decoded response. | The existing presence path also needs a feature-aware raw-advertisement implementation or migration to the maintained scanner library. |
| Our `comp_init.txt` has 81 commands, with a longest GATT write of 238 bytes. | Check the characteristic's maximum write-without-response size. Sending that command intact requires ATT MTU >=241; a negotiated MTU of 247 is sufficient. MTU 23 is not. |
| The Bosch session currently uses BlueZ `bluetoothctl` for bonding. | Proxy pairing must take place through the ESP32. The local adapter's existing bond is not evidence that the ESP32 is bonded. |
| Diagnostic access is decided by the bicycle. | A proxy does not unlock fields refused over BLE or make USB-only data available. |

The subscriber and raw-advertisement observations are source-level findings.
No failure on the user's installed proxy has been demonstrated; its firmware,
configuration and whether HA already uses it remain unknown.

## Two viable designs

**Standalone add-on, dedicated proxy.** Retain the MQTT add-on and introduce
an explicit Local Bluetooth / ESPHome transport selection. One process owns one
API connection manager for both bike data and tracker presence. The proxy must
not simultaneously serve HA's independent Bluetooth manager. This is the most
contained route for a first prototype of the existing application.

**Native HA integration, shared proxy.** Use HA's Bluetooth manager and normal
proxy routing, without opening a competing Bluetooth subscription from the
add-on. This better fits an existing shared proxy but requires moving the reader
into a custom integration or defining an explicit bridge. HA cannot simply lend
its in-process Bleak objects to the add-on container.

Do not enable automatic local/proxy failover initially. Pairing and connection
ownership must remain predictable, and tracker presence must not be marked
absent just because an active data session temporarily pauses scanning.

## First hardware check

`tools/esphome_proxy_check.py` retrieves API device information and the free-slot
snapshot using the add-on's existing encrypted API configuration. It does not
subscribe to advertisements, reserve a Bluetooth slot, connect to the bike,
pair, or send GATT writes. It reports capabilities as prerequisites, never as a
Bosch compatibility verdict. Secrets and other peripherals' addresses are not
printed. The probe's API-call sequence and cleanup have simulated tests; it has
not been run on the user's device.

In an environment with the pinned aioesphomeapi dependency installed:

```sh
python3 tools/esphome_proxy_check.py
```

It reads `/data/options.json` or `BLE_PROXY_HOST`, `BLE_PROXY_PORT`, and
`BLE_PROXY_KEY`. On another host, pass `--options` with an existing options file.
Do not put API keys in command-line arguments or committed files.

Next, using a dedicated proxy or a native HA test integration:

1. Check feature flags and active connection availability, then discover the
   selected Bosch address together with its advertised address type.
2. In the bicycle's pairing mode, establish the proxy-side bond. Confirm the
   iPhone's existing Flow pairing still works afterwards.
3. Read `eb21` and validate battery/odometer/service data with the existing
   decoder. This is the smallest useful success criterion.
4. Check MTU/write limits before the replayed session initialization. If too
   small, fail clearly; do not split arbitrary bytes. A smaller subscription
   sequence or correctly encoded MCSP segmentation needs separate validation.
5. Subscribe to `PUSH_NOTIFY`, initialize through `PUSH_WRITE`, and validate
   ride mode/range and bounded read-only enrichment. Unavailable fields remain
   unavailable. Always release the connection and notification callbacks.
6. Repeat after bike-off, Flow occupying the bike, Wi-Fi failure, cancellation,
   HA restart and proxy restart. Verify slots recover, the bond persists where
   supported, stale readings remain labelled and tracker guarding recovers.

The bike must be awake for the same read session; the proxy extends the radio
reach of that session rather than supplying power or an established wake command.

## Primary sources inspected

- [ESPHome proxy documentation](https://esphome.io/components/bluetooth_proxy/)
- [ESPHome 2026.11.0 subscriber ownership and raw advertisements](https://github.com/esphome/esphome/blob/2026.11.0/esphome/components/bluetooth_proxy/bluetooth_proxy.cpp)
- [bleak-esphome usage and routing](https://github.com/Bluetooth-Devices/bleak-esphome/blob/v4.1.0/docs/usage.md)
- [bleak-esphome 4.1.0 client implementation](https://github.com/Bluetooth-Devices/bleak-esphome/blob/v4.1.0/src/bleak_esphome/backend/client.py)
- [bleak-esphome dependency declarations](https://github.com/Bluetooth-Devices/bleak-esphome/blob/v4.1.0/pyproject.toml)
- [aioesphomeapi 46.3.0 API client](https://github.com/esphome/aioesphomeapi/blob/v46.3.0/aioesphomeapi/client.py)
- Local project: `proxy_presence_loop`, `ensure_bonded`, `read_snapshot`,
  `read_push`, and `ebike_battery/comp_init.txt`.
