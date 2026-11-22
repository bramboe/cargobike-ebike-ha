# My eBike

## Connection and setup

The add-on reads a Bosch Smart System bike through a bonded BlueZ Bluetooth
connection and publishes MQTT discovery entities. Tested development hardware:
Urban Arrow with BRC3600 LED Remote; other Smart System models are unverified.
No permanent USB connection is required or used by this runtime.

Use Home Assistant hardware with a working local Bluetooth adapter, or pass one
through to its VM. Install an MQTT broker. Open the My eBike panel, scan, select
the intended bike, enable pairing mode on the bike and press Pair. Selection is
stored by the panel: the former `bike_address` add-on option is no longer used.
The phone's Flow app can occupy the bike's BLE connection; let it disconnect if
reads fail. The ESPHome proxy listens for tracker presence only, not bike data.

## Existing entities

Battery %, last updated, Bluetooth address, odometer, distance to service, ride
mode and estimated range per mode keep their existing MQTT unique IDs and topics.
Historical readings remain visible when the bike is off. This is not evidence
that the bike is currently connected: consult Reader connection and reading age.

Cloud diagnostic sensor IDs also remain unchanged. New local fields have
separate `local_*` IDs and names ending in `(BLE)`, so a BMS health estimate is
not confused with a dealer capacity test. PON GPS data is optional and separate.

## BLE enrichment and component information

`ble_diagnostics` defaults to true and adds a bounded, best-effort read phase to
the existing BLE session. Supported fields include BMS state of health, full
charge cycles, pack voltage, battery/motor PCB temperature, remaining energy and
component model/serial/firmware. Each field has its own timestamp and capability
status. Explicit denial clears its displayed value; an old reading cannot look
fresh merely because a different field succeeded. Values expire after 24 hours.
DENIED/UNSUPPORTED/NO_ROUTE responses back off for six hours; reconnecting the
same bike does not hammer a protected field. Selecting another bike resets this
capability cache. Timeouts have a bounded three-attempt-per-session stop.

The extra fields are protocol research, **not yet hardware-validated over BLE on
the development bike**. A successful USB read is not proof of BLE access. Unreadable
fields stay unknown; there is no USB/cloud fallback masquerading as BLE. Existing
battery/odometer/range reads continue even if enrichment fails or is disabled.

Component changes are recorded when a new serial or firmware is read. A new
battery does not inherit the old pack's measurements. Software versions include
20.x.x as well as 19.x.x. Changing the selected bike clears its old retained data,
identity and history without changing the HA entity unique IDs.

## Ride history and time to service

Mileage samples and inferred rides are stored in the add-on's persistent data.
An inferred ride ends after 15 minutes without a newly observed distance change.
A long gap is labelled a **measurement interval**: it can contain multiple rides,
so the app does not claim exact start/stop times or an exact ride count.

Forecasts need at least seven calendar days, three observed rides/intervals and
positive mileage. The rolling window is up to 28 days and includes days not ridden:

- km/day = observed distance / elapsed calendar days;
- days to service = remaining service km / km/day;
- weeks = days / 7;
- rides/intervals remaining = remaining km / mean observed ride/interval distance.

For example, 10 km per ride at five rides/week gives about 50 km/week. A 200 km
service interval would then take about four weeks, rather than twenty days
regardless of riding frequency. Forecasts are estimates: incomplete BLE coverage
can merge rides, and changing usage changes the prediction. The panel labels
this uncertainty. History older than seven days without a new observation is
stale; insufficient/stale data yields an unknown estimate. Overdue service is
zero days. No forecast is seeded from the one-off USB research scan.

Per-ride battery consumption is in **percentage points** and percentage points/km,
not an invented Wh/km conversion. A charging increase invalidates consumption
for that interval. Odometer rollbacks, impossible jumps and out-of-order samples
are rejected. A new selected bike starts new history.

The Service due soon binary sensor activates at 200 km remaining. Days/weeks,
forecast diagnostics, mean observed ride distance and frequency are available as
MQTT entities for notifications. The forecast sensor attributes include the
method, sample duration, ride quality and recent history. Configure HA
notifications/automations using these entities; the add-on sends no messages or
controls charging sockets by itself.

## Interactive dashboard

The insight panel has Battery, Maintenance, Rides and Connection tabs. Select a
battery card to inspect its meaning, BLE timestamp and availability. The
maintenance scenario calculator lets you vary distance per ride and rides per
week; it never changes recorded history or Home Assistant forecast entities.

Filter recent observations by period and ride/interval type, inspect their
relative distance in the chart, or download the filtered rows as CSV. Only the
recent observations included in the status response (up to 50) are displayed.
Missing BLE data stays unknown. Connection details explain receiver, bicycle
and diagnostic availability, with a searchable list of supported/refused fields.
Your selected tab, filters and scenario survive automatic data refreshes.

Maintenance uses text and a blue emphasis marker: “Service approaching” at
200 km remaining or an estimated 14 days, and “Service interval reached” at
zero/negative remaining km. This is a planning reminder, not a mechanical fault
assessment. Negative mileage is shown as distance beyond the configured interval.
Settings → Display → Show maintenance hides the maintenance card, tab and cloud
service figure for all panel users. The preference survives restarts; collection,
MQTT entities and existing HA automations continue unchanged.

## Voltage and temperature warnings

Options (editable in add-on configuration):

| Option | Default | Meaning |
|---|---:|---|
| `ble_diagnostics` | true | Additional allowlisted BLE READ requests |
| `battery_temperature_low` | 0 | Warning below this measured temperature, °C |
| `battery_temperature_high` | 50 | Warning above this measured temperature, °C |
| `battery_voltage_low` | 30 | Warning below this pack voltage, V |
| `battery_voltage_high` | 43.5 | Warning above this pack voltage, V |
| `cooldown` | 120 | Minimum seconds between successful bike reads |
| `mqtt_host/port/user/pass` | automatic | Optional broker override |

Warning thresholds are configurable informational limits, not a charger safety
system. Use limits appropriate for the actual pack. The warnings stay unknown if
BLE denies the underlying measurement. Automatic charging control is not included:
charger-connected/charging-active decoding needs live validation first.

## Presence and alarm

The COMODULE/URBANARROW tracker is listened for passively; a permanent connection
for tracker motion was removed in 2.67. Tracker presence disappearing can trip an
armed alarm. The built-in BLE source is presence, not motion. External Home
Assistant contact/vibration/motion binary sensors can also be configured.

Per source: enabled, alarm/motion role, armed modes, always-on, invert,
unavailable-as-tamper and optional confirmation groups. Entry and exit delays
are configurable in the panel. An absence detected during exit delay remains
eligible after the delay ends. A pending alarm restored after restart becomes
triggered, rather than silently disarming; local alarm state is persisted too.

Receiver scan errors hold the last presence state and publish a separate receiver
problem diagnostic, rather than asserting bicycle theft. A healthy configured
proxy can keep the guard working. After receiver recovery there is a new grace
period. Loss of a receiver means reduced protection: use the receiver-problem
entity for an HA notification. This is not a certified security system.

`presence_alarm_seconds` is the unheard threshold while armed; compare it with
Longest silence while armed. `comodule_address`, `motion_off_delay`, optional
`ble_proxy_host/port/key` and the existing cloud options remain supported.

## Standalone use and code structure

`tools/bosch_mqtt_reader.py` delegates to the add-on reader so the standalone
entry point cannot diverge. Run it from a checkout with the dependencies in
`requirements_test.txt` (or the runtime versions from Dockerfile). On Linux,
use BlueZ, a broker, and writable `/data`; the supplied systemd service is an
example whose paths and broker settings must be edited.

Runtime orchestration lives in `bosch_mqtt_reader.py`; pure legacy decoders in
`telemetry.py`; bounded BLE READ enrichment in `ble_diagnostics.py`; explicit
address/decoding definitions in `diagnostics.py`; history/forecasts in
`history.py`; persisted derived data in `insights.py`; new discovery payloads in
`mqtt_insights.py`; alarm restart semantics in `alarm_state.py`; cloud parsing
in `cloud.py`; ingress HTML/JavaScript in `ui.py`.

BES3 address/scaling facts are attributed to
[rweijnen/bosch-bes3-reader](https://github.com/rweijnen/bosch-bes3-reader/tree/cd9a5510ae1091c467d8d5a586a23723c17a9249),
CC BY 4.0. The implementation adds no bike setting writes, RPCs or firmware tools.

This is unofficial community software, not affiliated with Bosch or Urban Arrow.
