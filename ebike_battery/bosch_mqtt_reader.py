#!/usr/bin/env python3
"""Urban Arrow (Bosch eBike) battery -> MQTT reader for Home Assistant. v1.1.

Use case: you arrive home, park the bike near this host; the battery % is read.

The host must be BONDED + TRUSTED with the bike (pair once with bluetoothctl).
A persistent scanner waits for the bike to advertise; on detection it connects,
reads the eb21 telemetry snapshot, publishes the battery % to MQTT, and
disconnects. The value is published RETAINED with no availability topic, so the
last reading (plus a "last updated" timestamp) stays visible in Home Assistant
until a new reading arrives — it never goes "unavailable". The on-disk bond
survives reboots.

Device selection:
- Set BIKE_ADDRESS to pin a specific bike, OR leave it empty to AUTO-DETECT the
  Bosch hub by its advertised name ("smart system eBike"). All candidates are
  logged, and the selected BLE address is published as a diagnostic sensor.

Config via environment variables (see the add-on / systemd unit):
  BIKE_ADDRESS (empty = auto), MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS,
  COOLDOWN, OP_TIMEOUT
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import threading
import time
import urllib.parse

import paho.mqtt.client as mqtt
from bleak import BleakClient, BleakScanner

from alarm_state import restore_state
from ble_diagnostics import DiagnosticReader
from insights import Insights
from mqtt_insights import publish as publish_insights_discovery
from telemetry import (_pb_fields as _pb_fields, parse_eb21 as parse_eb21,
                       parse_eb41_frame as parse_eb41_frame, _comp_string as _comp_string,
                       _lock_state as _lock_state, parse_components as parse_components,
                       parse_mode as parse_mode, parse_range as parse_range,
                       parse_power_profile as parse_power_profile)
from cloud import (_http_json as _http_json, _bnum as _bnum, _nested_num as _nested_num,
                   _parse_service_records as _parse_service_records,
                   _parse_capacity_tester as _parse_capacity_tester)
from ui import INDEX_HTML


try:
    import aiohttp  # HA core API client (feature F) + UI
    from aiohttp import web  # setup UI (Ingress)
except Exception:  # noqa: BLE001 - optional; reader still works without the UI
    aiohttp = None  # type: ignore[assignment]
    web = None  # type: ignore[assignment]

ADDRESS = os.getenv("BIKE_ADDRESS", "").strip()
AUTO = ADDRESS == ""
NAME_MATCH = "smart system"  # Bosch Smart System hub advertised name
EB21 = "0000eb21-eaa2-11e9-81b4-2a2ae2dbcce4"
EB41 = "0000eb41-eaa2-11e9-81b4-2a2ae2dbcce4"  # config: mode list + frame number
FIELD_BATTERY = 10

# Standard BLE Device Information Service (0x180A) — read once when connected.
DEVICE_INFO_CHARS = {
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "model": "00002a24-0000-1000-8000-00805f9b34fb",
    "serial": "00002a25-0000-1000-8000-00805f9b34fb",
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",
    "hardware": "00002a27-0000-1000-8000-00805f9b34fb",
}

# Bosch push channel: notifications carry the live-selected ride mode.
PUSH_NOTIFY = "00000011-eaa2-11e9-81b4-2a2ae2dbcce4"
PUSH_WRITE = "00000012-eaa2-11e9-81b4-2a2ae2dbcce4"
MODE_NAMES = {1: "Eco", 2: "Tour", 3: "Auto", 4: "Turbo"}

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")

COOLDOWN = float(os.getenv("COOLDOWN", "120"))
OP_TIMEOUT = float(os.getenv("OP_TIMEOUT", "15"))
SCAN_GAP = float(os.getenv("SCAN_GAP", "3"))

# COMODULE (URBANARROW) motion tracker — always-on, own battery.
COMODULE_ADDRESS = os.getenv("COMODULE_ADDRESS", "").strip()
COMODULE_NAME = "urbanarrow"
CHAR_155E = "0000155e-1212-efde-1523-785feabcd123"
MOTION_OFF_DELAY = float(os.getenv("MOTION_OFF_DELAY", "12"))
# Passive presence: a connection-free anti-theft layer. We just listen (scan) for
# the tracker's advertisement — zero extra module-battery drain, works even while
# disarmed. PRESENCE_GRACE = seconds the advert may go unheard before the bike is
# declared "out of range" (generous, so brief shared-adapter scan misses don't
# false-alarm). Re-checked every PRESENCE_GAP seconds with a short passive scan.
PRESENCE_GRACE = float(os.getenv("PRESENCE_GRACE", "600"))
PRESENCE_GAP = float(os.getenv("PRESENCE_GAP", "20"))
# While ARMED the alarm fires sooner: once the tracker has been unheard this long
# (the "in range" sensor keeps the longer PRESENCE_GRACE). Tune it against the
# "Longest silence while armed (24h)" sensor: keep it >= 1.5x that value.
PRESENCE_ALARM_GRACE = float(os.getenv("PRESENCE_ALARM_GRACE", "45") or 45)
# Scan cadence per mode (see _presence_mode). Guard = armed: near-continuous
# listening so a short alarm delay is safe (costs only the HA adapter, never the
# module). Paused = a fresh GPS fix says the bike is away: no point listening
# until GPS puts it home again, or the fix goes stale (then scan as usual).
PRESENCE_GAP_ARMED = float(os.getenv("PRESENCE_GAP_ARMED", "2") or 2)
PRESENCE_SCAN_ARMED = 10.0
CLOUD_FRESH_S = float(os.getenv("CLOUD_FRESH_S", "600") or 600)

DISC_PREFIX = "homeassistant"
NODE = "urban_arrow"
STATE_TOPIC = f"{NODE}/state"
STATUS_TOPIC = f"{NODE}/status"
MODE_TOPIC = f"{NODE}/mode"
RANGE_TOPIC = f"{NODE}/range"
MOTION_TOPIC = f"{NODE}/motion"
PRESENCE_TOPIC = f"{NODE}/present"
PRESENCE_GAP_TOPIC = f"{NODE}/presence_gap"   # longest silence while in range (24h)
MAIN_BATTERY_TOPIC = f"{NODE}/main_battery"
TRACKER_TOPIC = f"{NODE}/tracker"
ALARM_STATE_TOPIC = f"{NODE}/alarm/state"
ALARM_CMD_TOPIC = f"{NODE}/alarm/cmd"
ALARM_ATTR_TOPIC = f"{NODE}/alarm/attrs"      # {"reason": ..., "at": ...} on trip
TRACKER_REFRESH_TOPIC = f"{NODE}/tracker/refresh"
ARMED_STATES = ("armed_away", "armed_home", "armed_night")

_mqtt: "mqtt.Client | None" = None
# Set while connected to the broker (paho's network thread sets/clears it).
_mqtt_up = threading.Event()
# How long to wait after connecting for the broker's retained alarm state.
ALARM_RESTORE_WAIT = 5.0
ALARM_FILE = "/data/alarm.json"
INSIGHTS_FILE = "/data/insights.json"
INSIGHTS_TOPIC = f"{NODE}/insights"
READER_AVAILABILITY_TOPIC = f"{NODE}/reader/availability"
_insights = None
_ble_diagnostics = DiagnosticReader()
_DIAGNOSTICS_ENABLED = os.getenv("BLE_DIAGNOSTICS", "1") == "1"
_receiver_fault = False
_bike_generation = 0
_receiver_recovered_at = 0.0
_proxy_alive_at = 0.0

# Alarm state machine (HomeKit Security System via MQTT alarm_control_panel).
_alarm: dict[str, object] = {"state": "disarmed", "restored": False, "fired": False}
# Auto-detect: lock onto the first bike we successfully read, and back off bikes
# we fail to pair with (neighbours' "smart system eBike"s), to avoid churn.
_locked_addr: "str | None" = None
_pair_fail: dict[str, float] = {}
PAIR_RETRY_AFTER = 3600.0

# ---------------------------------------------- setup UI: config + state
DATA_FILE = "/data/ua.json"
INGRESS_PORT = int(os.getenv("INGRESS_PORT", "8099"))


def _write_json_atomic(path: str, data) -> None:
    """Write JSON so the file is either the old or the new version, never a torn
    mix: a crash or power cut mid-write must not corrupt the config or lose a
    rotated cloud refresh token (the old token is already revoked by then)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _load_cfg() -> dict:
    try:
        with open(DATA_FILE) as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def _save_cfg() -> None:
    try:
        _write_json_atomic(DATA_FILE, {
            "bike": _bike_addr, "tracker": _tracker_mac,
            "tracker_off": _tracker_off, "alarm_off": _alarm_off,
            "bike_off": _bike_off, "sensors": _sensors,
            "show_maintenance": _show_maintenance,
            "bike_model": _last.get("bike_model"),
            "bike_brand": _last.get("bike_brand"),
            "sku": _last.get("sku"),
            "product_code": _last.get("product_code"),
            "battery_model": _last.get("battery_model")})
    except Exception as err:  # noqa: BLE001
        log.warning("save config: %s", err)


# Persist the last shown readings to disk so the panel shows them INSTANTLY on the
# next start, instead of flashing dashes until the retained MQTT values arrive (or
# staying empty forever if the broker lost its retained messages). Only stable,
# display-relevant fields — NOT live flags (motion/bonded), which
# must reset to off on restart rather than wrongly read "connected".
LAST_FILE = "/data/last.json"
_PERSIST_KEYS = (
    "battery", "last_updated", "address", "odometer", "next_service",
    "frame_number", "hub_firmware", "part_number", "model_number",
    "max_torque", "max_power", "speed_limit",
    "module_firmware", "lock_label", "mode", "range", "bike_model", "bike_brand",
    "sku", "product_code", "product_name", "product_color", "battery_model",
    "drive_unit", "display", "components", "tracker_battery", "tracker_updated",
    "module_mac", "tracker_addr", "module_manufacturer", "module_hardware",
    # Last known presence: restored so a restart doesn't flash "out of range"
    # (presence_loop treats a restored True as "just heard" for one grace period).
    "tracker_present",
)


def _save_last() -> None:
    try:
        snapshot = {k: _last[k] for k in _PERSIST_KEYS if _last.get(k) is not None}
        _write_json_atomic(LAST_FILE, snapshot)
    except Exception as err:  # noqa: BLE001
        log.debug("save last: %s", err)


def _load_last() -> None:
    """Seed _last from the on-disk snapshot at startup (without clobbering values
    already set from config)."""
    try:
        with open(LAST_FILE) as fh:
            for k, v in json.load(fh).items():
                _last.setdefault(k, v)
    except Exception:  # noqa: BLE001
        pass


def _load_skus() -> dict:
    """Bundled article-code/product-code -> {name, color} lookup (skus.json)."""
    for path in ("/skus.json", os.path.join(os.path.dirname(__file__), "skus.json")):
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            continue
    return {}


_SKUS = _load_skus()


def _load_lines(name: str) -> list:
    """Load a bundled hex-per-line capture file (e.g. comp_init.txt, lock_on.txt)."""
    for path in ("/" + name, os.path.join(os.path.dirname(__file__), name)):
        try:
            with open(path) as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except Exception:  # noqa: BLE001
            continue
    return []


_COMP_INIT = _load_lines("comp_init.txt")


def _resolve_product() -> None:
    """Look up the friendly product name + colour from the bike's article code
    (preferred) or product code, and store them in _last."""
    entry = (_SKUS.get("frames", {}).get(_last.get("frame_number", ""))
             or _SKUS.get("skus", {}).get(_last.get("sku", ""))
             or _SKUS.get("product_codes", {}).get(_last.get("product_code", "")))
    if isinstance(entry, dict):
        if entry.get("name"):
            _last["product_name"] = entry["name"]
        if entry.get("color"):
            _last["product_color"] = entry["color"]
        if entry.get("sku") and not _last.get("sku"):
            _last["sku"] = entry["sku"]   # show the model SKU even if not read live


_cfg0 = _load_cfg()
_show_maintenance: bool = _cfg0.get("show_maintenance", True) is not False
# Bike BLE address to lock onto ("" = auto-detect by name). /data wins over env.
_bike_addr: "str | None" = (_cfg0.get("bike") or ADDRESS or "").strip() or None
# Tracker fixed module MAC (from the advertisement) — robust against its rotating
# BLE address. "" = auto-detect the first URBANARROW.
_tracker_mac: "str | None" = (_cfg0.get("tracker") or COMODULE_ADDRESS or "").strip() or None
_tracker_off: bool = bool(_cfg0.get("tracker_off", False))
# Bike removed/forgotten: pause all bike reading until one is (re-)added via the UI.
_bike_off: bool = bool(_cfg0.get("bike_off", False))
# Optional EXTERNAL motion source (feature F): an HA binary_sensor the user mounts
# on the bike (contact/vibration/motion). When it turns on we treat it like tracker
# motion — fully independent of BLE/the COMODULE. Entity id, "" = none.
_ext_motion: "str | None" = (_cfg0.get("ext_motion") or "").strip() or None
# Home Assistant core API via the Supervisor proxy (needs homeassistant_api: true).
SUPERVISOR_TOKEN: str = os.getenv("SUPERVISOR_TOKEN", "")
HA_API = "http://supervisor/core/api"
# Optional PON Connected Bike CLOUD poll (additive, no BLE): GPS location, module
# charge and speed over the internet. Needs an OAuth app client_id + a refresh_token
# (offline_access). Uses the refresh-token grant; rotated tokens persist to /data.
PON_BASE = "https://data-act.connected.pon.bike/api"
PON_TOKEN_URL = "https://consumer.login.pon.bike/oauth/token"
PON_CLIENT_ID: str = os.getenv("PON_CLIENT_ID", "").strip()
PON_BIKE_ID: str = os.getenv("PON_BIKE_ID", "").strip()
PON_POLL: float = float(os.getenv("PON_POLL", "120") or 120)
# When the tracker is heard over BLE (bike home/in range) we already know it's
# home, so poll the cloud only occasionally; poll fast only when it's away.
PON_POLL_HOME: float = float(os.getenv("PON_POLL_HOME", "1800") or 1800)
PON_FILE = "/data/pon.json"
CLOUD_TOPIC = f"{NODE}/cloud"
CLOUD_STATE_TOPIC = f"{NODE}/cloud/state"  # plain device_tracker state (moving/parked)


def _pon_load_refresh() -> "str | None":
    try:
        with open(PON_FILE) as fh:
            rt = (json.load(fh).get("refresh_token") or "").strip()
            if rt:
                return rt
    except Exception:  # noqa: BLE001
        pass
    return (os.getenv("PON_REFRESH", "").strip() or None)


def _pon_save_refresh(rt: str) -> None:
    try:
        _write_json_atomic(PON_FILE, {"refresh_token": rt})
    except Exception as err:  # noqa: BLE001
        log.warning("pon save: %s", err)


_pon_refresh: "str | None" = _pon_load_refresh()

# Optional Bosch SingleKey ID CLOUD poll (additive, no BLE): dealer-grade battery
# health + service data from the official Bosch Data Act API. Distinct from PON:
# PON is a re-seller proxy of the same platform; this talks to Bosch directly, which
# is the only surface exposing the service-book (SoH/cycles/next-service) and the
# diagnosis-field-data (capacity tester). Needs the user's own Data Act app client_id
# (portal.bosch-ebike.com/data-act/app) + a refresh_token from tools/bosch_login.py.
# Refresh-token grant only here — the one-time interactive PKCE login is out-of-band.
BOSCH_TOKEN_URL = ("https://p9.authz.bosch.com/auth/realms/obc/"
                   "protocol/openid-connect/token")
BOSCH_API = "https://api.bosch-ebike.com"
# Smart System (BES3) endpoints — our BRC3600 hub is Smart System, not eBike System 2.
BOSCH_BIKES_EP = "/bike-profile/smart-system/v1/bikes"
BOSCH_SERVICE_EP = "/service-book/smart-system/v1/service-records"
BOSCH_BIKEPASS_EP = "/bike-pass/smart-system/v1/bike-passes"
# Diagnosis Field Data prefix is unconfirmed in Bosch's PDF; try candidates in order
# and cache the one that answers (dealer-visit-gated, so 404 everywhere is normal).
BOSCH_CAPACITY_CANDIDATES = (
    "/diagnosis-field-data/smart-system/v1/capacity-testers",
    "/field-data/smart-system/v1/capacity-testers",
    "/smart-system/v1/capacity-testers",
)
BOSCH_CLIENT_ID: str = os.getenv("BOSCH_CLIENT_ID", "").strip()
BOSCH_POLL: float = float(os.getenv("BOSCH_POLL", "3600") or 3600)  # service data is slow
BOSCH_FILE = "/data/bosch.json"
BOSCH_TOPIC = f"{NODE}/bosch"


def _bosch_load_refresh() -> "str | None":
    try:
        with open(BOSCH_FILE) as fh:
            rt = (json.load(fh).get("refresh_token") or "").strip()
            if rt:
                return rt
    except Exception:  # noqa: BLE001
        pass
    return (os.getenv("BOSCH_REFRESH", "").strip() or None)


def _bosch_save_refresh(rt: str) -> None:
    try:
        _write_json_atomic(BOSCH_FILE, {"refresh_token": rt})
    except Exception as err:  # noqa: BLE001
        log.warning("bosch save: %s", err)


_bosch_refresh: "str | None" = _bosch_load_refresh()

# Registry of the rider's Bosch cloud bikes, refreshed by the Bosch poll, used to
# auto-match a BLE-scanned bike to its cloud identity. Each entry:
# {bike_id, remote_serial (normalised), name}. The BRC3600 LED remote we connect to
# over BLE reports its serial on DIS 0x2a25 == remoteControl.serialNumber in the
# Data Act bike profile — a deterministic key (verified live 2026-09-06).
_bosch_registry: list = []


def _norm_serial(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isalnum()).upper()


def _bosch_match(ble_serial):
    """The cloud bike whose remoteControl serial equals this BLE DIS serial, or None."""
    key = _norm_serial(ble_serial)
    if not key:
        return None
    return next((b for b in _bosch_registry if b.get("remote_serial") == key), None)


# Alarm (HomeKit Security System) is optional on top of the motion sensor.
_alarm_off: bool = bool(_cfg0.get("alarm_off", False))
# Passive presence alarm: when armed and the tracker advertisement disappears (bike
# taken out of BLE range), trip the alarm. The presence binary_sensor is always
# published; this flag only gates whether losing presence TRIPS the alarm.
_presence_alarm: bool = os.getenv("PRESENCE_ALARM", "1") == "1"

# ----------------------------------------------------------- sensor registry
# Alarmo-style unified sensor model. Every alarm/motion trigger source is a row
# here with the same per-sensor options, individually enable/disable-able:
#   - the BUILT-IN "presence" sensor (tracker advertisement disappears = out of
#     range). There is no BLE motion sensor: seeing motion over BLE needs a held
#     connection, which drains the module battery (removed in v2.67.0);
#   - any number of EXTERNAL HA binary_sensors the user mounts on the bike.
# apply_sensor() below is the single decision point all three loops call.
# Persisted in /data/ua.json under "sensors". Options per row:
#   enabled, role ("alarm" trips the alarm | "motion" dashboard-only),
#   always_on (trip even when disarmed), trigger_unavailable (external/presence:
#   an unavailable entity counts as active — tamper), invert (external), modes
#   (which armed states it's active in), group (optional double-check id).
_SENSOR_DEFAULTS = {
    "enabled": True, "role": "alarm", "always_on": False,
    "trigger_unavailable": False, "invert": False, "modes": list(ARMED_STATES),
    "group": "",
}


def _sensor_row(**over) -> dict:
    row = dict(_SENSOR_DEFAULTS)
    row.update(over)
    return row


def _migrate_sensors(cfg: dict) -> dict:
    """Return the sensor registry, migrating legacy ext_motion/presence_alarm the
    first time so existing users keep identical behaviour."""
    s = cfg.get("sensors")
    if isinstance(s, dict) and "builtin" in s:
        s["builtin"].pop("tracker_motion", None)    # pre-2.67 BLE motion row
        return s
    ext = []
    if _ext_motion:
        ext.append(_sensor_row(id="ext1", entity_id=_ext_motion, name=_ext_motion))
    return {
        "builtin": {
            "presence": _sensor_row(enabled=_presence_alarm),
        },
        "external": ext,
        "groups": {},
        "entry_delay": 0,
        "exit_delay": 0,
    }


_sensors: dict = _migrate_sensors(_cfg0)
# Per-source live "active" flag → the motion binary_sensor is the OR of these.
_motion_src: dict[str, bool] = {}
# Off-delay bookkeeping per source (stillness before a source clears its motion).
_src_off_since: "dict[str, float]" = {}
# Confirmation-group activity: gid -> {src_key: last_active_ts}.
_group_active: "dict[str, dict[str, float]]" = {}
# Alarm timing: when we last (re)armed (exit delay) + a pending trigger (entry delay).
_armed_at: float = 0.0
_pending_since: float = 0.0
_pending_reason: str = ""

# DEVELOPER MOTION TEST (motion_test): one connection-free look at every passive
# channel that might reveal movement — the tracker advert (payload, rate,
# scan-response), the Bosch hub waking up, and the PON cloud state — so a
# deliberate rest / move / rest session can be read back from the log. Holds the
# BLE adapter while on (bike reads and presence pause).
_motion_test: bool = os.getenv("MOTION_TEST", "0") == "1"
MOTION_TEST_POLL = 30.0   # PON poll interval (s) while the test runs
# While armed, poll PON this often: the GPS module reports to the cloud on its own
# when it is moved (seen in the 2026-09-27 motion tests: within ~30 s), so every
# fresh report is logged ("PON module report") to learn its routine pattern.
PON_POLL_ARMED = float(os.getenv("PON_POLL_ARMED", "30") or 30)
# Optional remote ESPHome Bluetooth proxy for the presence layer: lets HA hear the
# tracker from a second spot (e.g. the shed) so "in range" is more robust and the
# bike has to leave EVERY listener's range before the leave-range alarm fires.
# Host may be an IP or an .local name; key = the ESPHome device's API encryption
# key (noise PSK). Empty host = disabled. Connection-free w.r.t. the module.
_PROXY_HOST: str = os.getenv("BLE_PROXY_HOST", "").strip()
_PROXY_PORT: int = int(os.getenv("BLE_PROXY_PORT", "6053") or 6053)
_PROXY_KEY: str = os.getenv("BLE_PROXY_KEY", "").strip()
# Last time our tracker's advert was heard by ANY source (local adapter, held
# connection, or the remote BLE proxy). Drives the presence binary_sensor.
_tracker_seen_ts: float = 0.0
# "Heard just now": the presence scan runs every ~30 s, so a tracker heard within
# this window is physically next to the adapter — i.e. parked at home. Unlike the
# generous PRESENCE_GRACE (anti-false-alarm), this flips quickly on arrival/leave.
TRACKER_NEAR_S = float(os.getenv("TRACKER_NEAR_S", "120") or 120)


def _tracker_near(now: "float | None" = None) -> bool:
    """True if our tracker was heard over BLE within TRACKER_NEAR_S."""
    if not _tracker_seen_ts:
        return False
    return ((now if now is not None else time.time()) - _tracker_seen_ts) < TRACKER_NEAR_S
# Infer whether the bike's MAIN battery is inserted from the module-charge TREND
# (the module only charges when the main battery is in): rising/full = in, steadily
# falling = out (module on its own battery). Used to skip proactive module reads
# when on its own battery, so it lasts longer. Charge samples come from cloud
# (free, no BLE) and from BLE reads. "in" / "out" / None(unknown).
_charge_hist: list = []            # (ts, pct) rolling history
_main_battery_state: "str | None" = None
MAIN_BATT_WINDOW = float(os.getenv("MAIN_BATT_WINDOW", "2700") or 2700)  # 45 min

# Devices seen during scans, for the setup UI: address -> {name,rssi,kind,module_mac,ts}.
_discovered: dict[str, dict] = {}
# Last known values, for the setup UI status panel.
_last: dict[str, object] = {}

# Activity log: a persisted rolling history of usage/movement events (ride start/
# stop, left/arrived home, moved-while-parked), for the panel's Activities view
# and an HA sensor (state = latest event, attributes = the recent list).
ACTIVITY_FILE = "/data/activity.json"
ACTIVITY_TOPIC = f"{NODE}/activity"


def _load_activity() -> list:
    try:
        with open(ACTIVITY_FILE) as fh:
            d = json.load(fh)
            return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


_activity_log: list = _load_activity()
_pon_prev: dict = {}
if _activity_log:                    # show saved history immediately on startup
    _last["activity_log"] = _activity_log[-40:]


def _save_activity() -> None:
    try:
        _write_json_atomic(ACTIVITY_FILE, _activity_log[-80:])
    except Exception as err:  # noqa: BLE001
        log.debug("activity save: %s", err)


def _log_activity(etype: str, lat=None, lon=None, **extra) -> None:
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "type": etype}
    if lat is not None:
        ev["lat"] = round(lat, 5)
    if lon is not None:
        ev["lon"] = round(lon, 5)
    ev.update(extra)
    _activity_log.append(ev)
    del _activity_log[:-80]
    _save_activity()
    _last["activity_log"] = _activity_log[-40:]
    if _mqtt is not None:                # expose to HA as a sensor + attributes
        _mqtt.publish(ACTIVITY_TOPIC, json.dumps({
            "state": etype, "last_ts": ev["ts"],
            "events": _activity_log[-40:]}), retain=True)
    log.info("activity: %s", etype)


def _detect_activity(cloud: dict, *, near_home: bool = False) -> None:
    """Log usage/movement transitions from the cloud snapshot. First poll after a
    restart seeds the baseline silently (no spurious events). near_home = the
    tracker is heard over BLE right now, so a jump in the GPS fix is GPS noise or
    the arrival itself — never a "moved while parked"."""
    prev = _pon_prev
    ls = cloud.get("loc_state")
    home = cloud.get("home")
    lat, lon = cloud.get("latitude"), cloud.get("longitude")
    seeded = bool(prev)
    if seeded:
        if ls == "moving" and prev.get("loc_state") != "moving":
            _log_activity("ride_start", lat, lon)
        elif ls == "parked" and prev.get("loc_state") == "moving":
            _log_activity("ride_stop", lat, lon)
        if home is False and prev.get("home") is True:
            _log_activity("left_home", lat, lon)
        elif home is True and prev.get("home") is False:
            _log_activity("arrived_home", lat, lon)
        if (lat is not None and lon is not None and prev.get("lat") is not None
                and ls != "moving" and prev.get("loc_state") != "moving"
                and not near_home):
            d = _haversine(lat, lon, prev["lat"], prev["lon"])
            if d > 75:                       # a real displacement while parked
                _log_activity("moved", lat, lon, dist=round(d))
    prev["loc_state"] = ls
    prev["home"] = home
    if lat is not None:
        prev["lat"], prev["lon"] = lat, lon
    if not _last.get("activity_log"):
        _last["activity_log"] = _activity_log[-40:]


# Ride detection when the cloud reports no speed (PON's TELEMETRY history answers
# 403 unless that data category was shared with the app): a displacement of more
# than GPS_MOVE_M between two polls means the bike is being ridden. Hysteresis:
# "parked" only after GPS_STILL_POLLS still polls (a red light is not a stop), or
# at once when the tracker is heard at home over BLE.
GPS_MOVE_M = 75.0
GPS_STILL_POLLS = 2
_gps_track: dict = {"lat": None, "lon": None, "moving": False, "still": 0}


def _gps_moving(lat, lon, accuracy=0, *, near_home: bool = False) -> bool:
    """Moving/parked from consecutive cloud GPS fixes (see GPS_MOVE_M)."""
    tr = _gps_track
    if lat is None or lon is None:
        return bool(tr["moving"])
    if tr["lat"] is None:                       # first fix: baseline only
        tr.update(lat=lat, lon=lon, moving=False, still=0)
        return False
    dist = _haversine(tr["lat"], tr["lon"], lat, lon)
    tr["lat"], tr["lon"] = lat, lon
    if near_home:                               # heard at home right now: parked
        tr["moving"], tr["still"] = False, 0
        return False
    try:
        acc = float(accuracy or 0)
    except (TypeError, ValueError):
        acc = 0.0
    if dist > max(GPS_MOVE_M, 2 * acc):
        tr["moving"], tr["still"] = True, 0
    else:
        tr["still"] += 1
        if tr["still"] >= GPS_STILL_POLLS:
            tr["moving"] = False
    return bool(tr["moving"])


# The bike's brand/model is NOT broadcast over BLE (it lives in the maker's
# account/cloud), so the panel title is config-driven: the optional bike_model
# option wins; otherwise the page falls back to the bike's Device-Information
# manufacturer (e.g. "Bosch eBike Systems"). No hardcoded brand here.
_model_name: str = (os.getenv("BIKE_MODEL", "").strip()
                    or _cfg0.get("bike_model") or "").strip()
if _model_name:
    _last["bike_model"] = _model_name
if _cfg0.get("bike_brand"):
    _last["bike_brand"] = _cfg0["bike_brand"]
if _cfg0.get("sku"):
    _last["sku"] = _cfg0["sku"]
if _cfg0.get("product_code"):
    _last["product_code"] = _cfg0["product_code"]
if _cfg0.get("battery_model"):
    _last["battery_model"] = _cfg0["battery_model"]
_resolve_product()  # fill product_name/color from a restored sku/product_code
# Serialise BLE scans: the reader loop, tracker locate, and UI scans must not run
# a BleakScanner simultaneously (org.bluez "Operation already in progress").
_scan_lock = asyncio.Lock()
# Only one tracker-battery read at a time (bike-on, startup, or manual button).
_tracker_read_lock = asyncio.Lock()
# Wakes the PON cloud poll early (it sleeps up to 30 min while the bike is home)
# when BLE sees something change: bike switched on, tracker came/went.
_cloud_wake_evt = asyncio.Event()
_cloud_wake_ts = -1e9


def _cloud_wake() -> None:
    """Ask the cloud poll for a fresh position now (rate-limited)."""
    global _cloud_wake_ts
    now = time.monotonic()
    if now - _cloud_wake_ts < 60:
        return
    _cloud_wake_ts = now
    _cloud_wake_evt.set()
# Main asyncio loop ref, so MQTT-thread callbacks can schedule coroutines.
_loop: "asyncio.AbstractEventLoop | None" = None
# Strong references to background tasks: the event loop only keeps weak ones, so
# an unreferenced task can be garbage-collected mid-flight.
_tasks: "set[asyncio.Task]" = set()


def _task_done(task: "asyncio.Task") -> None:
    _tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background task %s failed: %s: %s", task.get_name(),
                  type(exc).__name__, exc, exc_info=exc)


def _spawn(coro, name: str) -> "asyncio.Task":
    """Run a coroutine in the background: keep a reference, log a crash."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_task_done)
    return task


async def _run_forever(name: str, factory, *, first_delay: float = 10.0) -> None:
    """Run a long-lived loop and restart it (with backoff) if it ever crashes,
    so one unexpected error can't silently switch off e.g. the anti-theft
    watcher until the add-on restarts. A normal return (feature not configured)
    ends it for good."""
    delay = first_delay
    while True:
        started = time.monotonic()
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.error("%s crashed (%s: %s) — restarting in %.0fs",
                      name, type(err).__name__, err, delay, exc_info=True)
        if time.monotonic() - started > 600:
            delay = first_delay           # it ran fine for a while: reset backoff
        await asyncio.sleep(delay)
        delay = min(delay * 2, 300.0)


def _supervise(name: str, factory) -> "asyncio.Task":
    return _spawn(_run_forever(name, factory), name)


def _env_float(key, default):
    try:
        value = float(os.getenv(key) or default)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def _ensure_insights():
    global _insights
    if _insights is None:
        _insights = Insights(INSIGHTS_FILE,
            temperature_low=_env_float("BATTERY_TEMPERATURE_LOW", 0),
            temperature_high=_env_float("BATTERY_TEMPERATURE_HIGH", 50),
            voltage_low=_env_float("BATTERY_VOLTAGE_LOW", 30),
            voltage_high=_env_float("BATTERY_VOLTAGE_HIGH", 43.5))
    return _insights


def _publish_insights():
    if _insights is None:
        return
    snapshot = _insights.snapshot()
    snapshot["receiver_health"] = "unavailable" if _receiver_fault and time.time() - _proxy_alive_at > 30 else "ok"
    _last["insights"] = snapshot
    if _mqtt is not None:
        _mqtt.publish(INSIGHTS_TOPIC, json.dumps(snapshot), retain=True)
    try:
        _insights.save()
    except OSError as err:
        log.warning("history save: %s", err)


def _connection(state, error=None):
    if _insights is not None:
        _insights.connection.update(state=state, error=error)


def _restore_local_alarm():
    try:
        with open(ALARM_FILE) as f:
            state = restore_state(json.load(f).get("state"))
        if state:
            _alarm.update(state=state, restored=True, fired=state == "triggered")
            _last["alarm"] = state
    except (OSError, ValueError, TypeError):
        pass


def _clear_bike_readings():
    global _bike_generation
    _bike_generation += 1
    # Keep alarm/tracker runtime state, clear everything tied to a selected bike.
    keep = {k: v for k, v in _last.items() if k in (
        "alarm", "motion", "tracker_battery", "tracker_updated", "tracker_present")}
    _last.clear()
    _last.update(keep)
    _ble_diagnostics.reset()
    _pair_fail.clear()
    if _insights is not None:
        _insights.reset()
    try:
        os.remove(LAST_FILE)
    except FileNotFoundError:
        pass
    if _mqtt is not None:
        for topic in (STATE_TOPIC, MODE_TOPIC, RANGE_TOPIC, BOSCH_TOPIC, INSIGHTS_TOPIC):
            _mqtt.publish(topic, "", retain=True)


def publish_status(status: str, present: str = "ON") -> None:
    """Publish a human-readable status + present(ON/OFF) for the status sensors."""
    if _mqtt is not None:
        _mqtt.publish(STATUS_TOPIC, json.dumps({"status": status, "present": present}),
                      retain=True)


def publish_motion(on: bool) -> None:
    """Publish the motion binary_sensor state (retained)."""
    if _mqtt is not None:
        _mqtt.publish(MOTION_TOPIC, "ON" if on else "OFF", retain=True)


def publish_present(on: bool) -> None:
    """Publish the tracker-present binary_sensor state (retained)."""
    if _mqtt is not None:
        _mqtt.publish(PRESENCE_TOPIC, "ON" if on else "OFF", retain=True)


def publish_main_battery(present: bool) -> None:
    """Publish the inferred main-battery-present binary_sensor (retained)."""
    if _mqtt is not None:
        _mqtt.publish(MAIN_BATTERY_TOPIC, "ON" if present else "OFF", retain=True)


_CHARGE_FILE = "/data/charge.json"


def _charge_load() -> None:
    """Restore the module-charge history from disk so the main-battery inference
    survives restarts (it otherwise loses its window every redeploy)."""
    global _charge_hist
    try:
        with open(_CHARGE_FILE) as fh:
            data = json.load(fh)
        _charge_hist = [(float(t), int(p)) for t, p in data if 0 <= int(p) <= 100]
        _charge_hist.sort(key=lambda x: x[0])
        _recompute_main_battery()
    except Exception:  # noqa: BLE001
        pass


def _charge_save() -> None:
    try:
        _write_json_atomic(_CHARGE_FILE, _charge_hist[-500:])
    except Exception as err:  # noqa: BLE001
        log.debug("charge save: %s", err)


def _record_charge(pct, ts: "float | None" = None) -> None:
    """Feed a module-charge sample (optionally historical, for cloud seeding)."""
    try:
        pct = int(pct)
    except Exception:  # noqa: BLE001
        return
    if not (0 <= pct <= 100):
        return
    _charge_hist.append((ts if ts is not None else time.time(), pct))
    _charge_hist.sort(key=lambda x: x[0])       # keep chronological (seeding adds older)
    _recompute_main_battery()


def _recompute_main_battery() -> None:
    """Infer whether the main battery is in from the charge trend. Rising or
    near-full = in (charging); a sustained drop over the window = out. Measured
    against the LATEST sample's time, so seeded/persisted history works the same."""
    global _main_battery_state
    if not _charge_hist:
        return
    now = _charge_hist[-1][0]
    # Keep a long horizon: a parked bike reports sparsely, so the reference point
    # can be many hours old. Trimming too aggressively would leave no comparison.
    cutoff = now - 48 * 3600
    while _charge_hist and _charge_hist[0][0] < cutoff:
        _charge_hist.pop(0)
    latest = _charge_hist[-1][1]
    ref = None                                  # newest sample older than the window
    for t, p in _charge_hist:
        if now - t >= MAIN_BATT_WINDOW:
            ref = p
    state = _main_battery_state
    if ref is not None:
        delta = latest - ref
        if delta > 0:
            state = "in"
        elif delta < -1:
            state = "out"
        elif latest >= 97:
            state = "in"
    elif latest >= 97:
        state = "in"
    if state != _main_battery_state and state is not None:
        _main_battery_state = state
        _last["main_battery"] = (state == "in")
        publish_main_battery(state == "in")
        log.info("main battery inferred: %s (module %s%%)", state, latest)


def publish_alarm(state: str) -> None:
    """Publish the alarm_control_panel state (retained)."""
    _last["alarm"] = state
    try:
        _write_json_atomic(ALARM_FILE, {"state": state, "at": time.time()})
    except OSError as err:
        log.warning("alarm save: %s", err)
    if _mqtt is not None:
        _mqtt.publish(ALARM_STATE_TOPIC, state, retain=True)


async def _alarm_restore() -> None:
    """Restore the alarm state from the broker's retained copy, then assert it.

    Waits for a real broker connection first: asserting the default ("disarmed")
    before the retained state could arrive would silently disarm an armed bike
    whenever the broker is slow or still starting."""
    while not _mqtt_up.is_set():
        await asyncio.sleep(0.5)
    deadline = time.monotonic() + ALARM_RESTORE_WAIT
    while not _alarm["restored"] and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if not _alarm["restored"]:
        _alarm["restored"] = True
        log.info("alarm: no retained state on the broker — starting %s", _alarm["state"])
    publish_alarm(str(_alarm["state"]))


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bosch-reader")


def _note_armed() -> None:
    """Record the moment we (re)armed, for the global exit delay, and wake the
    cloud poll so it switches to the armed cadence now (it may be sleeping for
    up to PON_POLL_HOME). Called from the MQTT thread too, hence threadsafe."""
    global _armed_at
    _armed_at = time.time()
    if _loop is not None:
        try:
            _loop.call_soon_threadsafe(_cloud_wake)
        except RuntimeError:                         # loop already closed
            pass


def _publish_alarm_reason(reason: str) -> None:
    """Expose WHY the alarm tripped as alarm_control_panel attributes, so a
    notification can say "out of range" vs "motion" instead of guessing."""
    if _mqtt is not None:
        _mqtt.publish(ALARM_ATTR_TOPIC, json.dumps({
            "reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}),
            retain=True)


def trip_alarm(reason: str) -> None:
    """Trip the alarm from any sensor. Honours the global entry delay by going to a
    'pending' state first (promoted by alarm_timing_loop); no-op once fired."""
    global _pending_since, _pending_reason
    if _alarm.get("fired") or _alarm["state"] == "pending":
        return
    _publish_alarm_reason(reason)
    delay = int(_sensors.get("entry_delay") or 0)
    if delay > 0 and _alarm["state"] in ARMED_STATES:
        _pending_since = time.time()
        _pending_reason = reason
        _alarm["state"] = "pending"
        publish_alarm("pending")
        log.info("alarm PENDING (%s) — %ss entry delay", reason, delay)
        return
    _alarm["fired"] = True
    _alarm["state"] = "triggered"
    publish_alarm("triggered")
    log.info("alarm TRIGGERED by %s", reason)


def _publish_motion_or() -> None:
    """Publish the single motion binary_sensor as the OR of all live sources."""
    on = any(_motion_src.values())
    _last["motion"] = on
    publish_motion(on)


def apply_sensor(active: bool, cfg: dict, *, src_key: str,
                 feed_motion: bool = True) -> None:
    """Single decision point for a trigger source (Alarmo-style). Feeds the shared
    motion binary_sensor (OR of all sources, unless feed_motion is False) with an
    off-delay debounce, then trips the alarm per this sensor's options."""
    if not cfg.get("enabled", True):
        if _motion_src.pop(src_key, False):
            _publish_motion_or()
        _src_off_since.pop(src_key, None)
        _group_active.get(cfg.get("group") or "", {}).pop(src_key, None)
        return
    now = time.time()
    # --- motion indicator (with per-source off-delay) ---
    if feed_motion:
        prev = _motion_src.get(src_key, False)
        if active:
            _src_off_since.pop(src_key, None)
            if not prev:
                _motion_src[src_key] = True
                _publish_motion_or()
        elif prev:
            t0 = _src_off_since.get(src_key)
            if t0 is None:
                _src_off_since[src_key] = now
            elif now - t0 >= MOTION_OFF_DELAY:
                _src_off_since.pop(src_key, None)
                _motion_src[src_key] = False
                _publish_motion_or()
    # --- alarm decision ---
    if cfg.get("role") != "alarm" or not active:
        return
    armed_here = _alarm["state"] in (cfg.get("modes") or ())
    if not (cfg.get("always_on") or (not _alarm_off and armed_here)):
        return
    # exit delay: ignore arming-based trips right after arming (never for always_on)
    exitd = int(_sensors.get("exit_delay") or 0)
    if not cfg.get("always_on") and exitd > 0 and now - _armed_at < exitd:
        return
    # optional double-check group: need N members active within the window
    gid = cfg.get("group") or ""
    if gid:
        grp = _sensors.get("groups", {}).get(gid, {})
        window = float(grp.get("window", 30) or 30)
        need = int(grp.get("min_active", 2) or 2)
        ga = _group_active.setdefault(gid, {})
        ga[src_key] = now
        if sum(1 for ts in ga.values() if now - ts <= window) < need:
            return
    trip_alarm(cfg.get("name") or src_key)


# ---------------------------------------------------------------- protobuf
# ------------------------------------------------------------------- MQTT
DEVICE = {
    "identifiers": [NODE],
    "name": "Urban Arrow",
    "manufacturer": "Bosch eBike Systems",
    "model": "Smart System (BRC3600)",
}


def _on_connect(client, _userdata, _flags, reason, _properties=None):
    rc = getattr(reason, "value", reason)
    if rc != 0:
        log.error("MQTT connection REFUSED (reason=%s) — check MQTT_USER/MQTT_PASS", reason)
        return
    _mqtt_up.set()
    client.publish(READER_AVAILABILITY_TOPIC, "online", retain=True)
    _publish_discovery(client)
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_publish_insights)
    else:
        _publish_insights()
    # Alarm: receive HomeKit/HA arm/disarm commands + restore the retained state.
    client.subscribe(ALARM_CMD_TOPIC)
    client.subscribe(ALARM_STATE_TOPIC)
    client.subscribe(TRACKER_REFRESH_TOPIC)
    # Restore the last measurement (retained) so the UI shows it after a restart.
    client.subscribe(STATE_TOPIC)
    client.subscribe(MODE_TOPIC)
    client.subscribe(RANGE_TOPIC)
    client.subscribe(MOTION_TOPIC)
    client.subscribe(TRACKER_TOPIC)
    if _alarm["restored"]:
        # Reconnect (e.g. the broker restarted and may have lost its retained
        # messages): re-assert the alarm so HA/HomeKit never show "unknown".
        client.publish(ALARM_STATE_TOPIC, str(_alarm["state"]), retain=True)
    log.info("connected to MQTT %s:%s", MQTT_HOST, MQTT_PORT)


def _on_disconnect(_client, _userdata, *args) -> None:
    """paho v2 passes (flags, reason, properties), v1 just (rc)."""
    was_up = _mqtt_up.is_set()
    _mqtt_up.clear()
    if was_up:
        reason = args[1] if len(args) >= 2 else (args[0] if args else "?")
        log.warning("MQTT disconnected (%s) — reconnecting in the background", reason)


def _on_message(_client, _userdata, msg) -> None:
    """Runs on paho's network thread: hand the message to the asyncio loop so all
    state (_alarm, _last, …) is only ever changed from one thread."""
    try:
        payload = msg.payload.decode(errors="ignore").strip()
    except Exception:  # noqa: BLE001
        return
    loop = _loop
    if loop is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(_handle_mqtt_message, msg.topic, payload)
            return
        except RuntimeError:        # loop shutting down
            return
    _handle_mqtt_message(msg.topic, payload)


def _handle_mqtt_message(topic: str, payload: str) -> None:
    if topic == ALARM_CMD_TOPIC:
        new = {"DISARM": "disarmed", "ARM_AWAY": "armed_away",
               "ARM_HOME": "armed_home", "ARM_NIGHT": "armed_night"}.get(payload.upper())
        if new:
            # A fresh command wins over a retained state that may still arrive.
            _alarm["restored"] = True
            _alarm["state"] = new
            _alarm["fired"] = False  # allow a fresh trigger after (re)arm/disarm
            if new in ARMED_STATES:
                _note_armed()        # start the exit-delay window
            publish_alarm(new)
            log.info("alarm command %s -> %s", payload, new)
    elif topic == TRACKER_REFRESH_TOPIC:
        log.info("manual tracker-battery refresh requested")
        trigger_tracker_refresh()
    elif topic == ALARM_STATE_TOPIC and not _alarm["restored"]:
        # First retained message after (re)connect = restore the previous state.
        state = restore_state(payload)
        if state is not None:
            _alarm.update(restored=True, state=state, fired=state == "triggered")
            _last["alarm"] = state
            log.info("alarm state restored: %s", state)
    elif topic == STATE_TOPIC:        # retained last reading -> show in the UI
        try:
            data = json.loads(payload)
            selected = _bike_addr or _locked_addr
            if selected and str(data.get("address") or "").upper() != selected.upper():
                return
            _last.update(data)
        except Exception:  # noqa: BLE001
            pass
    elif topic == MODE_TOPIC:
        if (_bike_addr or _locked_addr) and not _last.get("address"):
            return
        try:
            _last["mode"] = json.loads(payload).get("mode")
        except Exception:  # noqa: BLE001
            pass
    elif topic == RANGE_TOPIC:
        if (_bike_addr or _locked_addr) and not _last.get("address"):
            return
        try:
            _last["range"] = json.loads(payload)
        except Exception:  # noqa: BLE001
            pass
    elif topic == MOTION_TOPIC:
        _last["motion"] = payload == "ON"
    elif topic == TRACKER_TOPIC:
        try:
            d = json.loads(payload)
            _last["tracker_battery"] = d.get("battery")
            if d.get("ts"):
                _last["tracker_updated"] = d["ts"]
        except Exception:  # noqa: BLE001
            pass


def publish_alarm_discovery(client: mqtt.Client) -> None:
    """Publish (or remove, when disabled) the HomeKit alarm_control_panel."""
    topic = f"{DISC_PREFIX}/alarm_control_panel/{NODE}/alarm/config"
    if _alarm_off:
        client.publish(topic, "", retain=True)  # remove the accessory
        return
    client.publish(topic, json.dumps({
        "name": "Alarm",
        "unique_id": f"{NODE}_alarm",
        "state_topic": ALARM_STATE_TOPIC,
        "command_topic": ALARM_CMD_TOPIC,
        "json_attributes_topic": ALARM_ATTR_TOPIC,
        # Two meaningful modes for a bike: armed_away = loud, armed_home = silent.
        "supported_features": ["arm_away", "arm_home"],
        "code_arm_required": False,
        "code_disarm_required": False,
        "code_trigger_required": False,
        "icon": "mdi:shield-bike",
        "device": DEVICE,
    }), retain=True)


def _publish_discovery(client: mqtt.Client) -> None:
    publish_insights_discovery(client, node=NODE, prefix=DISC_PREFIX,
                              topic=INSIGHTS_TOPIC, availability=READER_AVAILABILITY_TOPIC, device=DEVICE)
    # No availability_topic on purpose: the retained value stays shown (with its
    # timestamp) until the next reading — it never reports "unavailable".
    def cfg(obj_id: str, name: str, **extra) -> None:
        payload = {
            "name": name,
            "unique_id": f"{NODE}_{obj_id}",
            "state_topic": STATE_TOPIC,
            "value_template": "{{ value_json.%s }}" % obj_id,
            "device": DEVICE,
            **extra,
        }
        client.publish(
            f"{DISC_PREFIX}/sensor/{NODE}/{obj_id}/config", json.dumps(payload), retain=True
        )

    cfg("battery", "Battery", device_class="battery",
        unit_of_measurement="%", state_class="measurement")
    cfg("last_updated", "Last updated", device_class="timestamp")
    cfg("address", "Bluetooth address", icon="mdi:bluetooth", entity_category="diagnostic")
    cfg("frame_number", "Frame number", icon="mdi:identifier", entity_category="diagnostic")
    cfg("lock_label", "eBike Lock", icon="mdi:bike-fast")
    cfg("part_number", "Part number", icon="mdi:barcode", entity_category="diagnostic")
    cfg("hub_firmware", "Hub firmware", icon="mdi:chip", entity_category="diagnostic")
    cfg("module_firmware", "Module firmware", icon="mdi:chip", entity_category="diagnostic")
    cfg("odometer", "Odometer", device_class="distance", unit_of_measurement="km",
        state_class="total_increasing", icon="mdi:counter")
    cfg("next_service", "Next service in", unit_of_measurement="km", icon="mdi:wrench-clock")
    cfg("max_torque", "Max torque", unit_of_measurement="Nm",
        icon="mdi:engine", entity_category="diagnostic")
    cfg("max_power", "Max power", device_class="power",
        unit_of_measurement="W", icon="mdi:flash", entity_category="diagnostic")
    cfg("speed_limit", "Assist speed limit", device_class="speed",
        unit_of_measurement="km/h", icon="mdi:speedometer", entity_category="diagnostic")

    # Ride mode sensor — reads MODE_TOPIC (its own retained topic so the last
    # known mode stays shown between rides).
    client.publish(
        f"{DISC_PREFIX}/sensor/{NODE}/mode/config",
        json.dumps({
            "name": "Ride mode",
            "unique_id": f"{NODE}_mode",
            "state_topic": MODE_TOPIC,
            "value_template": "{{ value_json.mode }}",
            "icon": "mdi:speedometer",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Estimated range per mode (km) — reads RANGE_TOPIC.
    for key, label in (("eco", "Range Eco"), ("tour", "Range Tour+"),
                       ("auto", "Range Auto"), ("turbo", "Range Turbo")):
        client.publish(
            f"{DISC_PREFIX}/sensor/{NODE}/range_{key}/config",
            json.dumps({
                "name": label,
                "unique_id": f"{NODE}_range_{key}",
                "state_topic": RANGE_TOPIC,
                "value_template": "{{ value_json.%s }}" % key,
                "unit_of_measurement": "km",
                "icon": "mdi:map-marker-distance",
                "device": DEVICE,
            }),
            retain=True,
        )

    # Bosch SingleKey ID cloud sensors (battery health + service) — read BOSCH_TOPIC,
    # its own retained JSON so the last known values survive between slow polls. Only
    # published when the Bosch cloud is configured; otherwise the topic stays empty
    # and the entities simply show "unknown" (harmless).
    def bcfg(obj_id: str, name: str, **extra) -> None:
        client.publish(
            f"{DISC_PREFIX}/sensor/{NODE}/{obj_id}/config",
            json.dumps({
                "name": name,
                "unique_id": f"{NODE}_{obj_id}",
                "state_topic": BOSCH_TOPIC,
                "value_template": "{{ value_json.%s | default('') }}" % obj_id,
                "device": DEVICE,
                **extra,
            }),
            retain=True,
        )

    bcfg("battery_soh", "Battery health", unit_of_measurement="%",
         state_class="measurement", icon="mdi:battery-heart-variant")
    bcfg("battery_cycles", "Battery charge cycles", state_class="total_increasing",
         icon="mdi:battery-sync")
    bcfg("battery_lifetime_wh", "Battery energy delivered", device_class="energy",
         unit_of_measurement="Wh", state_class="total_increasing", icon="mdi:battery-charging")
    bcfg("battery_model", "Battery model", entity_category="diagnostic",
         icon="mdi:battery")
    bcfg("motor_hours", "Motor hours", unit_of_measurement="h",
         state_class="total_increasing", icon="mdi:engine")
    bcfg("power_on_hours", "System power-on", unit_of_measurement="h",
         state_class="total_increasing", entity_category="diagnostic", icon="mdi:power")
    bcfg("last_software_update", "Last software update", device_class="timestamp",
         entity_category="diagnostic")
    bcfg("software_version", "Software version", entity_category="diagnostic",
         icon="mdi:chip")
    bcfg("capacity_tested_wh", "Capacity tester result", device_class="energy_storage",
         unit_of_measurement="Wh", entity_category="diagnostic", icon="mdi:battery-check")

    # Clear retained discovery for retired sensors so HA drops the orphans: the
    # first 2.48.0 cut's non-existent Bosch fields, and the cloud "Next service in"
    # that duplicated the Bluetooth one (same name -> next_service_in_3).
    for _gone in ("battery_measured_wh", "battery_nominal_wh", "next_service_days",
                  "software_update", "last_service_date", "last_service_odometer",
                  "last_service_dealer", "next_service_km"):
        client.publish(f"{DISC_PREFIX}/sensor/{NODE}/{_gone}/config", "", retain=True)

    # Presence diagnostic: longest silence while armed and in range (24 h), i.e.
    # measured at the guard cadence that decides false alarms. Keep the armed
    # grace (presence_alarm_seconds) at >= 1.5x this value.
    client.publish(
        f"{DISC_PREFIX}/sensor/{NODE}/presence_gap/config",
        json.dumps({
            "name": "Longest silence while armed (24h)",
            "unique_id": f"{NODE}_presence_gap",
            "state_topic": PRESENCE_GAP_TOPIC,
            "unit_of_measurement": "s",
            "device_class": "duration",
            "state_class": "measurement",
            "entity_category": "diagnostic",
            "icon": "mdi:bluetooth-audio",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Activities — latest event as state, the recent list as attributes (for a
    # Lovelace markdown card on any HA dashboard).
    client.publish(
        f"{DISC_PREFIX}/sensor/{NODE}/last_activity/config",
        json.dumps({
            "name": "Last activity",
            "unique_id": f"{NODE}_last_activity",
            "state_topic": ACTIVITY_TOPIC,
            "value_template": "{{ value_json.state }}",
            "json_attributes_topic": ACTIVITY_TOPIC,
            "icon": "mdi:history",
            "device": DEVICE,
        }),
        retain=True,
    )

    publish_alarm_discovery(client)

    # Clean up the removed eBike Lock switch (clear its retained discovery so HA
    # drops the orphaned entity). The lock write is not possible — Ed25519-signed.
    client.publish(f"{DISC_PREFIX}/switch/{NODE}/lock/config", "", retain=True)

    # Status text sensor (current phase) — reads STATUS_TOPIC, not STATE_TOPIC.
    client.publish(
        f"{DISC_PREFIX}/sensor/{NODE}/status/config",
        json.dumps({
            "name": "Status",
            "unique_id": f"{NODE}_status",
            "state_topic": STATUS_TOPIC,
            "value_template": "{{ value_json.status }}",
            "icon": "mdi:bike",
            "entity_category": "diagnostic",
            "device": DEVICE,
        }),
        retain=True,
    )
    # Motion sensor — on while the COMODULE tracker reports movement (anti-theft).
    client.publish(
        f"{DISC_PREFIX}/binary_sensor/{NODE}/motion/config",
        json.dumps({
            "name": "Motion",
            "unique_id": f"{NODE}_motion",
            "state_topic": MOTION_TOPIC,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "motion",  # HomeKit maps this to a Motion Sensor
            "icon": "mdi:bike-fast",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Presence — passive anti-theft: ON while the tracker advertisement is heard
    # (bike in BLE range), OFF when it disappears. No connection = no module drain.
    client.publish(
        f"{DISC_PREFIX}/binary_sensor/{NODE}/present/config",
        json.dumps({
            "name": "In range",
            "unique_id": f"{NODE}_present",
            "state_topic": PRESENCE_TOPIC,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "presence",
            "icon": "mdi:map-marker-radius",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Main battery present (inferred from the module-charge trend) — the module
    # only charges when the bike's main battery is in. ON = in (charging/full).
    client.publish(
        f"{DISC_PREFIX}/binary_sensor/{NODE}/main_battery/config",
        json.dumps({
            "name": "Main battery",
            "unique_id": f"{NODE}_main_battery",
            "state_topic": MAIN_BATTERY_TOPIC,
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "power",
            "icon": "mdi:car-battery",
            "entity_category": "diagnostic",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Tracker (COMODULE) own battery — drives the low-battery alarm cutoff.
    client.publish(
        f"{DISC_PREFIX}/sensor/{NODE}/tracker_battery/config",
        json.dumps({
            "name": "Tracker battery",
            "unique_id": f"{NODE}_tracker_battery",
            "state_topic": TRACKER_TOPIC,
            "value_template": "{{ value_json.battery }}",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "entity_category": "diagnostic",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Manual one-shot "refresh module battery" button (connects to the tracker once).
    client.publish(
        f"{DISC_PREFIX}/button/{NODE}/tracker_refresh/config",
        json.dumps({
            "name": "Refresh module battery",
            "unique_id": f"{NODE}_tracker_refresh",
            "command_topic": TRACKER_REFRESH_TOPIC,
            "icon": "mdi:battery-sync",
            "entity_category": "diagnostic",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Clean up the removed eBike-lock TEST buttons (clear their retained discovery).
    for obj in ("lock_test_on", "lock_test_kiox", "lock_test_off"):
        client.publish(f"{DISC_PREFIX}/button/{NODE}/{obj}/config", "", retain=True)

    # Awake/reachable indicator — on = bike advertising (on/in range), off = not.
    client.publish(
        f"{DISC_PREFIX}/binary_sensor/{NODE}/awake/config",
        json.dumps({
            "name": "Awake",
            "unique_id": f"{NODE}_awake",
            "state_topic": STATUS_TOPIC,
            "value_template": "{{ value_json.present }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
            "device": DEVICE,
        }),
        retain=True,
    )

    # Cloud (PON Connected Bike) entities — only when the cloud poll is configured;
    # otherwise clear them so no orphaned "unknown" entities linger.
    cloud_on = bool(PON_CLIENT_ID and _pon_refresh)
    if cloud_on:
        client.publish(
            f"{DISC_PREFIX}/device_tracker/{NODE}/location/config",
            json.dumps({
                "name": "Location",
                "unique_id": f"{NODE}_location",
                "state_topic": CLOUD_STATE_TOPIC,
                "json_attributes_topic": CLOUD_TOPIC,
                "source_type": "gps",
                "icon": "mdi:map-marker",
                "device": DEVICE,
            }), retain=True)
        client.publish(
            f"{DISC_PREFIX}/sensor/{NODE}/cloud_speed/config",
            json.dumps({
                "name": "Speed",
                "unique_id": f"{NODE}_cloud_speed",
                "state_topic": CLOUD_TOPIC,
                "value_template": "{{ value_json.speed | default(0) }}",
                "device_class": "speed",
                "unit_of_measurement": "km/h",
                "icon": "mdi:speedometer",
                "device": DEVICE,
            }), retain=True)
        client.publish(
            f"{DISC_PREFIX}/binary_sensor/{NODE}/in_use/config",
            json.dumps({
                "name": "In use",
                "unique_id": f"{NODE}_in_use",
                "state_topic": CLOUD_TOPIC,
                "value_template": "{{ 'ON' if value_json.in_use else 'OFF' }}",
                "device_class": "moving",
                "icon": "mdi:bike-fast",
                "device": DEVICE,
            }), retain=True)
        client.publish(
            f"{DISC_PREFIX}/sensor/{NODE}/cloud_module_charge/config",
            json.dumps({
                "name": "Module charge (cloud)",
                "unique_id": f"{NODE}_cloud_module_charge",
                "state_topic": CLOUD_TOPIC,
                "value_template": "{{ value_json.module_charge | default('') }}",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "entity_category": "diagnostic",
                "device": DEVICE,
            }), retain=True)
    else:
        for obj, dom in (("location", "device_tracker"), ("cloud_speed", "sensor"),
                         ("in_use", "binary_sensor"),
                         ("cloud_module_charge", "sensor")):
            client.publish(f"{DISC_PREFIX}/{dom}/{NODE}/{obj}/config", "", retain=True)

    # Remove sensors published by earlier versions.
    for old in ("battery2",):
        client.publish(f"{DISC_PREFIX}/sensor/{NODE}/{old}/config", "", retain=True)


def make_mqtt() -> mqtt.Client:
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="urban_arrow_reader")
    except AttributeError:  # paho-mqtt < 2.0
        client = mqtt.Client(client_id="urban_arrow_reader")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    # Non-blocking: paho's network thread makes the first connection and keeps
    # retrying, so a broker that is still starting (after a host reboot) or is
    # restarting never takes the add-on down with it.
    client.will_set(READER_AVAILABILITY_TOPIC, "offline", retain=True)
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


# -------------------------------------------------------------------- bonding
async def _bctl(*args: str, timeout: float = 20.0) -> str:
    """Run a bluetoothctl command, return its output (empty on failure)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out.decode(errors="ignore")
    except Exception as err:  # noqa: BLE001 - bluetoothctl missing/timeout
        log.debug("bluetoothctl %s: %s", args, err)
        return ""


async def _bctl_pair(address: str) -> str:
    """Run an interactive bluetoothctl session that registers an agent and
    pairs (Just Works needs an agent to auto-confirm). Returns the output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as err:  # noqa: BLE001
        return f"bluetoothctl unavailable: {err}"
    seq = [
        ("power on", 1.0),
        ("agent KeyboardDisplay", 0.3),
        ("default-agent", 0.3),
        ("scan on", 6.0),
        (f"pair {address}", 12.0),
        (f"trust {address}", 1.0),
        ("scan off", 0.3),
        ("quit", 0.3),
    ]
    try:
        for cmd, delay in seq:
            proc.stdin.write((cmd + "\n").encode())
            await proc.stdin.drain()
            await asyncio.sleep(delay)
    except Exception:  # noqa: BLE001
        pass
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return out.decode(errors="ignore")
    except asyncio.TimeoutError:
        proc.kill()
        return "(bluetoothctl session timed out)"


async def ensure_bonded(address: str) -> bool:
    """Make sure BlueZ has a trusted bond for the bike (Just Works pairing).

    Runs whenever the bike is detected, so pairing happens at the right moment
    (bike awake / in pairing mode) without restarting — no missed window.
    """
    if "Bonded: yes" in await _bctl("info", address, timeout=10):
        # Already bonded: just (re)trust and connect immediately. Do NOT
        # disconnect here — that only added latency and caused org.bluez
        # "In Progress" races, and with the bike on only briefly the read
        # window would close before we got to connect.
        await _bctl("trust", address, timeout=8)
        return True
    log.warning("not bonded — pairing %s now (bike must be in PAIRING MODE)", address)
    publish_status("Not paired — put the bike in PAIRING MODE", "ON")
    out = await _bctl_pair(address)
    tail = " | ".join(ln.strip() for ln in out.splitlines()
                      if any(k in ln for k in ("Pair", "pair", "Fail", "Agent", "Bonded", "Error")))
    log.info("pair log: %s", tail[-400:] or "(no relevant output)")
    bonded = "Bonded: yes" in await _bctl("info", address, timeout=10)
    log.info("pairing attempt result: bonded=%s", bonded)
    if not bonded:
        return False
    # The pairing session holds the link open; free the single BLE slot so the
    # follow-up read gets a clean connection (and the bike advertises again).
    await _bctl("disconnect", address, timeout=8)
    await asyncio.sleep(1)
    return True


# -------------------------------------------------------------------- BLE
def _pb_strings(b: bytes) -> list[str]:
    """Extract protobuf string fields (0a <len> <ascii>) from a push frame —
    the bike's component-info records (model, battery, serials, …)."""
    out: list[str] = []
    i = 0
    while i < len(b) - 1:
        if b[i] == 0x0A:
            ln = b[i + 1]
            if 3 <= ln <= 40 and i + 2 + ln <= len(b):
                chunk = b[i + 2:i + 2 + ln]
                if all(32 <= c < 127 for c in chunk):
                    out.append(chunk.decode())
                    i += 2 + ln
                    continue
        i += 1
    return out


async def read_push(client: BleakClient) -> tuple[str | None, dict[str, int] | None]:
    """Subscribe to the Bosch push channel and capture the live ride mode and
    the estimated range per mode.

    Best-effort: enables notifications, replays the app's stream subscriptions
    (so the bike pushes the mode (9809) and range (9857) attributes), listens
    briefly, and returns (mode, ranges). Either may be None if nothing arrived.
    """
    latest: dict[str, object] = {"mode": None, "range": None, "model": None,
                                 "battery_model": None, "drive_unit": None,
                                 "display": None}
    count = {"n": 0}
    generation = _bike_generation
    buf = bytearray()  # full stream, for cross-frame component records

    def cb(_char, data: bytearray) -> None:
        count["n"] += 1
        b = bytes(data)
        if _DIAGNOSTICS_ENABLED:
            _ble_diagnostics.feed(b)
        buf.extend(b)
        log.debug("push frame %d: %s", count["n"], b.hex())
        m = parse_mode(b)
        if m:
            latest["mode"] = m
        r = parse_range(b)
        if r:
            latest["range"] = r
        for svalue in _pb_strings(b):  # component info (model, battery, …)
            if svalue == "Urban Arrow":
                latest["model"] = svalue
            elif svalue.startswith("PowerPack"):
                latest["battery_model"] = svalue.replace(" Frame", "").strip()
            elif "Performance Line" in svalue or "Drive Unit" in svalue:
                latest["drive_unit"] = svalue.replace("Drive Unit", "").strip() or svalue
            elif svalue.startswith("Kiox") or svalue.startswith("Nyon") or "Purion" in svalue:
                latest["display"] = svalue

    try:
        for attempt in range(2):  # tolerate a "service discovery not done yet" race
            try:
                await client.start_notify(PUSH_NOTIFY, cb)
                break
            except Exception as err:  # noqa: BLE001
                if attempt == 0:
                    log.debug("start_notify retry after: %s", err)
                    await asyncio.sleep(1.5)
                else:
                    raise
        log.debug("subscribed to push channel %s; sending subscriptions", PUSH_NOTIFY)
        # Replayed verbatim from the Bosch app (Flow.pklg): the registration
        # header, then the ride-mode (9809) and per-mode range (9857) attribute
        # subscriptions. The bike then pushes 30 04 98 09 08 <level> and
        # 98 57 0a 04 <eco><tour><auto><turbo>.
        # Base subscriptions for ride mode (9809) + range (9857), then replay the
        # app's full session-init request sequence (comp_init.txt) which makes the
        # bike push its static component config (brand/SKU/product/per-component fw).
        for cmd in (_COMP_INIT + ["30054180980960", "30054180985760"]):
            try:
                await client.write_gatt_char(PUSH_WRITE, bytes.fromhex(cmd), response=False)
                await asyncio.sleep(0.08)   # pace the writes like the app does
            except Exception as err:  # noqa: BLE001
                log.debug("sub write failed: %s", err)
        await asyncio.sleep(10)   # give the component-config dump time to arrive
        if _DIAGNOSTICS_ENABLED and _insights is not None and generation == _bike_generation:
            try:
                result = await _ble_diagnostics.collect(client, PUSH_WRITE)
                if generation == _bike_generation:
                    _insights.enrich(result)
            except Exception as err:
                log.debug("BLE diagnostic enrichment failed: %s", err)
        await client.stop_notify(PUSH_NOTIFY)
        log.debug("push channel: %d frame(s), mode=%s range=%s",
                  count["n"], latest["mode"], latest["range"])
        if generation != _bike_generation:
            return None, None
        for src, dst in (("battery_model", "battery_model"),
                         ("drive_unit", "drive_unit"), ("display", "display")):
            if latest[src]:
                _last[dst] = latest[src]
        # Bike brand from the component info (attr 186c, e.g. "Urban Arrow") — the
        # actual brand IS in the BLE push stream. Used as the panel title unless a
        # bike_model is configured. Read from the bike, generic across brands.
        brand = _comp_string(bytes(buf), 0x186C)
        if brand:
            _last["bike_brand"] = brand
        sku = _comp_string(bytes(buf), 0x1875)        # base SKU / article code, e.g. BUA0652
        if sku:
            _last["sku"] = sku
        pcode = _comp_string(bytes(buf), 0x182A)      # Bosch product code, PON-SMA-URBANARROW
        if pcode:
            _last["product_code"] = pcode
        prof = parse_power_profile(bytes(buf))  # drive-unit assist map: torque/power/speed
        if prof:
            _last.update(prof)
            log.info("power profile: %s", prof)
        _resolve_product()  # map sku/product_code -> friendly name + colour
        comps = parse_components(bytes(buf))  # per-subsystem firmware + date
        # eBike Lock state (read-only): the bike reports it on 0d1c when locked.
        # Only trust it when a full config push happened (brand/components seen).
        if brand or comps:
            mk = _lock_state(bytes(buf))
            if mk is None:
                _last["lock_state"], _last["lock_label"] = "unlocked", "unlocked"
            else:
                meth = "phone+Kiox" if (mk & 0x0F) else "phone"
                _last["lock_state"], _last["lock_label"] = "locked", f"locked ({meth})"
        if comps:
            _last["components"] = {**_last.get("components", {}), **comps}
        if brand or latest["battery_model"] or comps:
            log.info("components: brand=%s battery=%s drive=%s display=%s specs=%s",
                     brand, latest["battery_model"], latest["drive_unit"],
                     latest["display"], comps)
            _save_cfg()  # persist so the specs show immediately after a restart
        else:  # diagnostic: did the component-config push arrive at all?
            strs = _pb_strings(bytes(buf))
            log.info("components: none captured (%d push frames, %d strings: %s)",
                     count["n"], len(strs), strs[:10])
    except Exception as err:  # noqa: BLE001
        log.warning("push read failed: %s: %s", type(err).__name__, err)
    return latest["mode"], latest["range"]  # type: ignore[return-value]


async def read_snapshot(mqtt_client: mqtt.Client, device) -> bool:
    """Connect, read eb21 battery + push-channel ride mode, publish (retained)."""
    if _last.get("address") and str(_last["address"]).upper() != device.address.upper():
        _clear_bike_readings()
    log.info("connecting to %s (%s) ...", device.address, device.name or "?")
    publish_status(f"Connected to {device.name or 'bike'} — reading…", "ON")
    generation = _bike_generation
    raw: bytes | None = None
    mode: str | None = None
    ranges: dict[str, int] | None = None
    async with BleakClient(device, timeout=20.0) as client:
        log.info("reading eb21 snapshot ...")
        for attempt in range(3):
            try:
                raw = bytes(await asyncio.wait_for(client.read_gatt_char(EB21), timeout=10))
                break
            except Exception as err:  # noqa: BLE001
                log.warning("read attempt %d -> %s: %s", attempt + 1, type(err).__name__, err)
                await asyncio.sleep(2)
        mode, ranges = await read_push(client)
        if generation != _bike_generation:
            return False
        if "device_info" not in _last:  # static — read once
            info = {}
            for key, uuid in DEVICE_INFO_CHARS.items():
                try:
                    val = bytes(await client.read_gatt_char(uuid)).decode(errors="ignore").strip()
                    if val:
                        info[key] = val
                except Exception:  # noqa: BLE001
                    pass
            if generation != _bike_generation:
                return False
            if info:
                info["name"] = device.name or ""
                _last["device_info"] = info
                # Promote to top-level so they ride along in the STATE publish
                # (and become HA sensors). "serial" (DIS 2a25) is Bosch's part
                # number; the bike's frame number comes from eb41 instead.
                if info.get("firmware"):
                    _last["hub_firmware"] = info["firmware"]
                if info.get("serial"):
                    _last["part_number"] = info["serial"]
                    # BLE↔cloud auto-match: DIS 0x2a25 == remoteControl.serialNumber.
                    m = _bosch_match(info["serial"])
                    if m:
                        _last["cloud_matched"] = True
                        _last["cloud_bike_id"] = m["bike_id"]
                        log.info("cloud match: BLE bike = Bosch bike %s", m["bike_id"])
                if info.get("model"):
                    _last["model_number"] = info["model"]
                log.info("device info: %s", info)
        if "frame_number" not in _last:  # static — read once from eb41
            try:
                fr = parse_eb41_frame(bytes(await client.read_gatt_char(EB41)))
                if generation != _bike_generation:
                    return False
                if fr:
                    _last["frame_number"] = fr
                    log.info("frame number: %s", fr)
                    _resolve_product()  # frame -> product name/colour/SKU lookup
            except Exception as err:  # noqa: BLE001
                log.debug("eb41 read failed: %s", err)
    if generation != _bike_generation:
        return False
    if raw is None:
        log.warning("eb21 read failed (bond missing/untrusted? re-pair via bluetoothctl)")
        publish_status("Read failed — bike awake?", "ON")
        return False
    log.debug("eb21 raw: %s", raw.hex())
    data = parse_eb21(raw)
    battery = data.get("battery")
    if battery is None:
        log.warning("no battery field in payload: %s", raw.hex())
        publish_status("Read failed — no battery field", "ON")
        return False
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    state = {
        "battery": battery,
        "last_updated": now,
        "address": device.address,
    }
    if "odometer" in data:
        state["odometer"] = data["odometer"]
    if "next_service" in data:
        state["next_service"] = data["next_service"]
    for k in ("frame_number", "hub_firmware", "part_number",
              "model_number", "module_firmware", "lock_label",
              "max_torque", "max_power", "speed_limit"):
        if _last.get(k):
            state[k] = _last[k]
    mqtt_client.publish(STATE_TOPIC, json.dumps(state), retain=True)
    log.info("published %s", state)
    _last.update(state)
    if _insights is not None:
        _insights.observe(state, identity=device.address.upper())
        _publish_insights()
    _last["bonded"] = True
    if mode is not None:
        mqtt_client.publish(MODE_TOPIC, json.dumps({"mode": mode}), retain=True)
        log.info("ride mode: %s", mode)
        _last["mode"] = mode
    if ranges is not None:
        mqtt_client.publish(RANGE_TOPIC, json.dumps(ranges), retain=True)
        log.info("range km: %s", ranges)
        _last["range"] = ranges
    publish_status(f"Battery {battery}% read at {time.strftime('%Y-%m-%d %H:%M')}", "ON")
    _save_last()   # persist immediately so a fresh reading survives a restart
    return True


def _tracker_module_mac(adv) -> "str | None":
    """The COMODULE's fixed module MAC from its advertisement (company 0x020F)."""
    raw = (adv.manufacturer_data or {}).get(0x020F)
    if raw and len(raw) >= 6:
        return ":".join(f"{b:02x}" for b in raw[:6]).upper()
    return None


def _record(device, adv) -> "str | None":
    """Record a discovered bike/tracker for the setup UI. Returns its kind."""
    global _tracker_seen_ts
    nl = (device.name or "").lower()
    if NAME_MATCH in nl:
        kind = "bike"
        mac = None
    elif COMODULE_NAME in nl:
        kind = "tracker"
        mac = _tracker_module_mac(adv)
    else:
        return None
    _discovered[device.address] = {
        "address": device.address, "name": device.name or "",
        "rssi": adv.rssi, "kind": kind, "module_mac": mac, "ts": time.time(),
    }
    # Any scan that hears OUR tracker counts for presence — otherwise a bike or UI
    # scan holding the adapter would look like silence to the presence guard.
    if kind == "tracker" and _tracker_mac and (mac or "").upper() == _tracker_mac.upper():
        _tracker_seen_ts = time.time()
    return kind


async def find_bike(timeout: float = 15.0):
    """Scan with a FRESH scanner (started+stopped per call, so it can't wedge
    after a connect) and return the bike's BLEDevice, or None."""
    found: dict[str, object] = {}
    ev = asyncio.Event()
    seen: set[str] = set()

    def cb(device, adv) -> None:
        kind = _record(device, adv)
        if kind != "bike":
            return
        if _bike_addr is None:  # auto-detect by name
            if _locked_addr and device.address.upper() != _locked_addr.upper():
                return  # locked onto our bike — ignore other "smart system eBike"s
            if device.address not in seen:
                seen.add(device.address)
                log.info("bike candidate: %s  '%s'  rssi=%s",
                         device.address, device.name or "", adv.rssi)
        elif device.address.upper() != _bike_addr.upper():
            return
        found["device"] = device
        ev.set()

    async with _scan_lock, BleakScanner(detection_callback=cb):
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    return found.get("device")


def _err_text(err: BaseException) -> str:
    """'Type: message' — with a readable text for the message-less timeouts."""
    msg = str(err).strip()
    if not msg and isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        msg = "timed out (bike out of reach or busy?)"
    return f"{type(err).__name__}: {msg or 'no details'}"


def _read_retry_delay(fails: int) -> float:
    """Pause before the next scan: SCAN_GAP normally, growing after consecutive
    failed reads so a bike that won't answer isn't hammered (which also starves
    the presence/tracker scans on the shared adapter)."""
    if fails <= 0:
        return SCAN_GAP
    return min(SCAN_GAP * (2 ** min(fails, 8)), max(COOLDOWN, 30.0))


async def ble_loop(mqtt_client: mqtt.Client) -> None:
    """Scan (fresh each cycle); on detection, bond if needed and read once."""
    global _locked_addr
    last_ok = 0.0
    fails = 0
    was_seen = False
    log.info("scanning (%s)", _bike_addr or "auto-detect 'smart system eBike'")
    while True:
        try:
            if _bike_off:                     # bike removed — pause until re-added
                _connection("no_bike")
                _connection("no_bike")
                publish_status("No bike added", "OFF")
                await asyncio.sleep(4)
                continue
            if _motion_test:                  # dev: let motion_test own the adapter
                await asyncio.sleep(4)
                continue
            device = await find_bike(timeout=15.0)
            auto = _bike_addr is None
            if device is not None and not was_seen:
                _cloud_wake()                 # bike switched on: fresh cloud position
            was_seen = device is not None
            if device is None:
                fails = 0
                _connection("off_or_out_of_range")
                _connection("off_or_out_of_range")
                publish_status("Bike not found (off or out of range)", "OFF")
            elif time.time() - last_ok < COOLDOWN:
                # Seen recently; wait out the cooldown before reading again.
                publish_status("Bike in range — waiting (cooldown)", "ON")
            elif (auto and _locked_addr is None and device.address in _pair_fail
                  and time.time() - _pair_fail[device.address] < PAIR_RETRY_AFTER):
                # A nearby eBike we couldn't pair with (a neighbour's) — skip it.
                publish_status("Ignoring an unknown nearby eBike", "OFF")
            else:
                log.info("bike seen — connecting to read")
                if not await ensure_bonded(device.address):
                    _connection("pairing_required")
                    _pair_fail[device.address] = time.time()
                    fails += 1
                elif await read_snapshot(mqtt_client, device):
                    last_ok = time.time()
                    fails = 0
                    if auto and _locked_addr is None:
                        _locked_addr = device.address
                        _pair_fail.clear()
                        log.info("locked onto bike %s", device.address)
                    # Bike is on -> refresh the tracker's own battery too (low-power).
                    await read_tracker_battery()
                else:
                    fails += 1
        except Exception as err:  # noqa: BLE001
            fails += 1
            _connection("receiver_unavailable" if "BluetoothNotAvailable" in type(err).__name__ else "read_failed", _err_text(err))
            log.warning("cycle failed: %s", _err_text(err))
            publish_status("Connection failed — keep the bike on, retrying…", "ON")
        await asyncio.sleep(_read_retry_delay(fails))


# -------------------------------------------------------------------- COMODULE
async def find_comodule(timeout: float = 12.0):
    """Scan for the URBANARROW tracker. If a module MAC is configured, match it
    (robust against the rotating BLE address); else take the first one. Records
    all trackers for the setup UI. Returns the BLEDevice or None."""
    found: dict[str, object] = {}
    seen: dict[str, int] = {}
    ev = asyncio.Event()

    def cb(device, adv) -> None:
        if _record(device, adv) != "tracker":
            return
        seen[device.address] = getattr(adv, "rssi", 0)
        if _tracker_mac and (_tracker_module_mac(adv) or "").upper() != _tracker_mac.upper():
            return  # not our tracker
        # Record the stable module MAC (adv) + current BLE address for the UI.
        _last["module_mac"] = _tracker_module_mac(adv) or _last.get("module_mac")
        _last["tracker_addr"] = device.address
        found["device"] = device
        ev.set()

    log.info("comodule scan: looking for tracker (filter=%s)", _tracker_mac or "any")
    async with _scan_lock, BleakScanner(detection_callback=cb):
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    if seen:
        log.info("comodule scan: trackers seen: %s",
                 ", ".join(f"{a}@{r}dBm" for a, r in seen.items()))
    else:
        log.info("comodule scan: no URBANARROW tracker heard by the local adapter")
    return found.get("device")


async def _read_module_dis(client) -> None:
    """Read the COMODULE's Device Information once -> _last module_* fields."""
    mapping = {"module_firmware": "firmware", "module_manufacturer": "manufacturer",
               "module_hardware": "hardware", "module_model": "model"}
    if all(_last.get(dst) for dst in mapping):
        return
    for dst, key in mapping.items():
        if _last.get(dst):
            continue
        try:
            val = bytes(await client.read_gatt_char(
                DEVICE_INFO_CHARS[key])).decode(errors="ignore").strip()
            if val:
                _last[dst] = val
        except Exception:  # noqa: BLE001
            pass
    log.info("module info: fw=%s mfr=%s hw=%s", _last.get("module_firmware"),
             _last.get("module_manufacturer"), _last.get("module_hardware"))


async def read_tracker_battery(proactive: bool = True) -> None:
    """One-shot, low-power refresh of the tracker's own battery %. Used while the
    bike is on (its main battery present, so the module is charging). Briefly connects, grabs a 0xC6 status
    frame, then disconnects so the tracker can sleep again. Proactive reads are
    skipped when the main battery is inferred OUT (module on its own battery), to
    spare it — manual refreshes (proactive=False) always run."""
    if _tracker_off:
        return  # tracker disabled
    if proactive and _main_battery_state == "out":
        return  # module on its own battery — don't spend a connection on a read
    if _tracker_read_lock.locked():
        return  # a read is already in progress
    async with _tracker_read_lock:
        await _do_read_tracker_battery()


async def _do_read_tracker_battery() -> None:
    try:
        target = await find_comodule()
    except Exception as err:  # noqa: BLE001 - BlueZ busy; this is best-effort
        log.debug("tracker battery scan failed: %s", err)
        return
    if target is None:
        return
    got = {"done": False}

    def cb(_c, data: bytearray) -> None:
        b = bytes(data)
        if len(b) > 2 and b[1] == 0xC6 and 0 <= b[2] <= 100:
            _last["tracker_battery"] = b[2]
            _last["tracker_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            _record_charge(b[2])
            if _mqtt is not None:
                _mqtt.publish(TRACKER_TOPIC, json.dumps(
                    {"battery": b[2], "ts": _last["tracker_updated"]}), retain=True)
            got["done"] = True

    try:
        async with BleakClient(target, timeout=20.0) as client:
            await client.start_notify(CHAR_155E, cb)
            await _read_module_dis(client)  # static module specs, read once
            for _ in range(8):
                await asyncio.sleep(1)
                if got["done"]:
                    break
            await client.stop_notify(CHAR_155E)
        if got["done"]:
            log.info("tracker battery refreshed: %s%%", _last.get("tracker_battery"))
    except Exception as err:  # noqa: BLE001
        log.debug("tracker battery refresh failed: %s", err)


def trigger_tracker_refresh() -> None:
    """Schedule a one-shot tracker-battery read from any thread (MQTT button /
    UI). Safe to call repeatedly — the read itself is single-flighted."""
    if _loop is not None:
        try:
            _loop.call_soon_threadsafe(
                lambda: _spawn(read_tracker_battery(proactive=False), "tracker_refresh"))
        except Exception as err:  # noqa: BLE001
            log.debug("tracker refresh schedule failed: %s", err)


async def scan_tracker_present(timeout: float = 8.0) -> bool | None:
    """Passive: briefly scan for our tracker's advertisement. Returns True if heard.
    No connection is made, so this costs the module zero battery. Quiet (no per-scan
    log) since it runs continuously for the presence layer."""
    found = {"hit": False}
    ev = asyncio.Event()

    def cb(device, adv) -> None:
        if _record(device, adv) != "tracker":
            return
        if _tracker_mac and (_tracker_module_mac(adv) or "").upper() != _tracker_mac.upper():
            return  # not our tracker
        _last["module_mac"] = _tracker_module_mac(adv) or _last.get("module_mac")
        _last["tracker_addr"] = device.address
        found["hit"] = True
        ev.set()

    try:
        async with _scan_lock, BleakScanner(detection_callback=cb):
            try:
                await asyncio.wait_for(ev.wait(), timeout)
            except asyncio.TimeoutError:
                pass
    except Exception as err:  # noqa: BLE001
        log.debug("presence scan failed: %s", err)
        return None
    return found["hit"]


# Presence-layer state (module-level so tests can drive _presence_eval directly).
# present: last published "in range"; had: the tracker was heard since start (or
# restored as present) — the alarm only fires on a real present -> gone edge;
# alarm_edge: already fired for the current absence; gaps: (ts, silence) of the
# last 24 h measured while guarding, for the "Longest silence" diagnostic;
# mode/guard_since: current scan cadence and when guarding started.
_pres: dict = {"present": None, "had": False, "alarm_edge": False,
               "prev_seen": 0.0, "gaps": [], "gap_pub": None, "mode": None,
               "guard_since": 0.0}
# Latest GPS verdict from the PON poll: home (inside zone.home) and when polled.
_cloud_home: dict = {"home": None, "at": 0.0}


def _presence_guarding() -> bool:
    """Would the presence sensor trip the alarm right now (armed in its modes)?"""
    cfg = _sensors["builtin"]["presence"]
    if not cfg.get("enabled", True) or cfg.get("role") != "alarm":
        return False
    return cfg.get("always_on") or (not _alarm_off
                                    and _alarm["state"] in (cfg.get("modes") or ()))


def _presence_mode(now: float) -> str:
    """'paused' while a fresh GPS fix puts the unheard bike away from home,
    'guard' while armed, else 'normal'."""
    ch = _cloud_home
    if (not _tracker_near(now) and ch["home"] is False
            and now - ch["at"] < CLOUD_FRESH_S):
        return "paused"
    return "guard" if _presence_guarding() else "normal"


def _presence_seed(now: float) -> None:
    """On start, trust the last known presence for one grace period instead of
    flashing "out of range" before the first scan hit (a restart used to publish
    OFF, which would false-alarm anything keyed on it)."""
    global _tracker_seen_ts
    if _last.get("tracker_present") is True:
        _tracker_seen_ts = max(_tracker_seen_ts, now)
        _pres.update(present=True, had=True, prev_seen=_tracker_seen_ts)


def _presence_eval(now: float) -> None:
    """Decide presence from _tracker_seen_ts (updated by the local scan, a held
    connection or the remote proxy). Connection-free by design."""
    p = _pres
    # Loss of the receiver is diagnostic failure, not proof of bicycle theft.
    if _receiver_fault and now - _proxy_alive_at > 30:
        return
    if _receiver_recovered_at and now - _receiver_recovered_at < PRESENCE_ALARM_GRACE:
        return
    seen = _tracker_seen_ts
    if seen > p["prev_seen"]:                       # a fresh hit since last round
        # Only gaps fully inside a guard stretch: the slower disarmed cadence
        # would overstate the silences that matter for false alarms.
        if (p["mode"] == "guard" and 0 < p["guard_since"] <= p["prev_seen"]
                and seen - p["prev_seen"] < PRESENCE_GRACE):
            p["gaps"].append((seen, seen - p["prev_seen"]))
        p["prev_seen"] = seen
        p["had"] = True
        p["alarm_edge"] = False                     # heard again: re-arm the edge
    p["gaps"] = [(t, g) for t, g in p["gaps"] if now - t <= 86400]
    longest = int(round(max((g for _t, g in p["gaps"]), default=0)))
    if longest != p["gap_pub"]:
        p["gap_pub"] = longest
        if _mqtt is not None:
            _mqtt.publish(PRESENCE_GAP_TOPIC, str(longest), retain=True)
    unseen = now - seen
    is_present = unseen < PRESENCE_GRACE
    if is_present != p["present"]:
        p["present"] = is_present
        _last["tracker_present"] = is_present
        publish_present(is_present)
        log.info("presence: %s", "in range" if is_present else "OUT OF RANGE")
    # Alarm: once per absence, as soon as the tracker has been unheard for
    # PRESENCE_ALARM_GRACE (shorter than the "in range" grace). Only on a real edge
    # (it WAS here) — arming while the bike is away never trips. apply_sensor only
    # trips when armed; feed_motion=False: leaving range isn't "motion".
    exit_delay = int(_sensors.get("exit_delay") or 0)
    if (_alarm["state"] in ARMED_STATES and not _sensors["builtin"]["presence"].get("always_on")
            and now - _armed_at < exit_delay):
        return
    if p["had"] and not p["alarm_edge"] and unseen >= PRESENCE_ALARM_GRACE:
        p["alarm_edge"] = True
        log.info("presence: tracker unheard for %ds", int(unseen))
        apply_sensor(True, _sensors["builtin"]["presence"],
                     src_key="presence", feed_motion=False)


async def presence_loop() -> None:
    """Passive anti-theft layer: track whether the tracker is in BLE range by
    listening for its advertisement (no connection = no module-battery drain, works
    even while disarmed). Publishes binary_sensor.urban_arrow_in_range and — when
    armed — trips the alarm once the tracker has been unheard for a while."""
    global _tracker_seen_ts, _receiver_fault, _receiver_recovered_at
    near_prev: "bool | None" = None
    _presence_seed(time.time())
    while True:
        try:
            if _tracker_off:
                if _pres["present"] is not False:
                    _pres["present"] = False
                    _last["tracker_present"] = False
                    publish_present(False)
                _pres.update(had=False, alarm_edge=False)
                await asyncio.sleep(PRESENCE_GAP)
                continue
            if _motion_test:
                # A diagnostic probe holds the scan adapter continuously, so presence
                # scans would starve and falsely flip to "out of range" (and could
                # trip the alarm). Hold the last state while a probe runs.
                await asyncio.sleep(PRESENCE_GAP)
                continue
            mode = _presence_mode(time.time())
            if mode != _pres["mode"]:
                log.info("presence scan: %s", mode)
                _pres["mode"] = mode
                _pres["guard_since"] = time.time() if mode == "guard" else 0.0
            # Seen by any source? A scan hit (_record stamps _tracker_seen_ts for
            # every scan); the remote BLE proxy does too.
            if mode != "paused":
                hit = await scan_tracker_present(PRESENCE_SCAN_ARMED if mode == "guard" else 8.0)
                if _receiver_fault and hit is not None:
                    _receiver_recovered_at = time.time()
                _receiver_fault = hit is None
                if hit:
                    _tracker_seen_ts = time.time()
            now = time.time()
            near = _tracker_near(now)
            if near_prev is not None and near != near_prev:
                _cloud_wake()             # just arrived / just left: fresh position
            near_prev = near
            _presence_eval(now)
        except Exception as err:  # noqa: BLE001
            log.warning("presence loop: %s: %s", type(err).__name__, err)
        await asyncio.sleep(PRESENCE_GAP_ARMED if _pres["mode"] == "guard"
                            else PRESENCE_GAP)


def _proxy_adv_is_tracker(adv) -> bool:
    """True if an ESPHome-proxy advertisement is our COMODULE tracker (company
    0x020F whose payload starts with the module MAC; else fall back to the name)."""
    md = getattr(adv, "manufacturer_data", None)
    items: list = []
    if isinstance(md, dict):
        items = list(md.items())
    elif isinstance(md, (list, tuple)):
        for it in md:
            try:
                items.append((it[0], it[1]))
            except Exception:  # noqa: BLE001
                pass
    for cid, val in items:
        if cid in (0x020F, 527):
            h = bytes(val).hex()
            if _tracker_mac:
                return h.startswith(_tracker_mac.replace(":", "").lower())
            return True
    nm = (getattr(adv, "name", "") or "").lower()
    return ("urbanarrow" in nm) and not _tracker_mac


async def proxy_presence_loop() -> None:
    """Optional: subscribe to a remote ESPHome Bluetooth proxy and feed the presence
    layer when it hears our tracker. Extends 'in range' coverage with zero module
    cost. Fully isolated: any failure just disables the proxy, local presence stays."""
    if not _PROXY_HOST or not _PROXY_KEY:
        return
    try:
        from aioesphomeapi import APIClient, ReconnectLogic
        from zeroconf.asyncio import AsyncZeroconf
    except Exception as err:  # noqa: BLE001
        log.warning("BLE proxy disabled (libs unavailable): %s", err)
        return

    dbg = {"t": 0.0}

    def on_adv(adv) -> None:
        global _proxy_alive_at
        _proxy_alive_at = time.time()
        if _tracker_off:
            return
        try:
            match = _proxy_adv_is_tracker(adv)
            if match:
                globals()["_tracker_seen_ts"] = time.time()
            now = time.monotonic()
            if now - dbg["t"] > 60:            # diagnostic: see the proxy advert format
                md = getattr(adv, "manufacturer_data", None)
                nm = getattr(adv, "name", "") or ""
                if match or "urban" in nm.lower() or (isinstance(md, dict)
                        and (0x020F in md or 527 in md)):
                    dbg["t"] = now
                    log.info("proxy adv: name=%r match=%s mfr=%r", nm, match, md)
        except Exception as err:  # noqa: BLE001
            log.debug("proxy on_adv: %s", err)

    try:
        azc = AsyncZeroconf()
        cli = APIClient(_PROXY_HOST, _PROXY_PORT, "", noise_psk=_PROXY_KEY,
                        zeroconf_instance=azc.zeroconf)

        async def on_connect() -> None:
            try:
                # Returns an unsubscribe callable (not awaitable).
                cli.subscribe_bluetooth_le_advertisements(on_adv)
                log.info("BLE proxy connected: %s:%s", _PROXY_HOST, _PROXY_PORT)
            except Exception as err:  # noqa: BLE001
                log.warning("BLE proxy subscribe failed: %s", err)

        async def on_disconnect(expected: bool) -> None:
            log.info("BLE proxy disconnected (%s)", _PROXY_HOST)

        reconnect = ReconnectLogic(client=cli, on_connect=on_connect,
                                   on_disconnect=on_disconnect,
                                   zeroconf_instance=azc.zeroconf, name=_PROXY_HOST)
        await reconnect.start()
        while True:
            await asyncio.sleep(3600)
    except Exception as err:  # noqa: BLE001
        log.warning("BLE proxy loop failed (%s): %s", _PROXY_HOST, err)


async def _ha_get(path: str):
    """GET the Home Assistant core API via the Supervisor proxy. None on failure."""
    if not SUPERVISOR_TOKEN or aiohttp is None:
        return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(HA_API + path,
                             headers={"Authorization": "Bearer " + SUPERVISOR_TOKEN},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 200:
                    return await r.json()
                log.debug("HA API %s -> %s", path, r.status)
    except Exception as err:  # noqa: BLE001
        log.debug("HA API %s failed: %s", path, err)
    return None


# binary_sensor classes that make sense as a bike-mounted theft sensor.
_EXT_CLASSES = ("motion", "moving", "vibration", "door", "window", "opening",
                "occupancy", "presence", "tamper", "sound")


async def list_ha_motion_entities() -> list:
    """Return candidate HA binary_sensors the user could mount on the bike."""
    states = await _ha_get("/states")
    out = []
    if not isinstance(states, list):
        return out
    for st in states:
        eid = st.get("entity_id", "")
        if not eid.startswith("binary_sensor."):
            continue
        attrs = st.get("attributes", {}) or {}
        dc = attrs.get("device_class")
        # Offer matching device-classes first, but allow any binary_sensor too.
        out.append({"entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "device_class": dc,
                    "state": st.get("state"),
                    "match": dc in _EXT_CLASSES})
    out.sort(key=lambda e: (not e["match"], e["name"].lower()))
    return out


# Last raw HA state seen per external entity (for the UI's live per-row readout).
_ext_live: "dict[str, str]" = {}


def _ext_key(cfg: dict) -> str:
    """Stable src_key for an external sensor row."""
    return "ext:" + (cfg.get("id") or cfg.get("entity_id") or "")


async def ext_motion_loop() -> None:
    """Poll every configured external HA binary_sensor and feed it through the
    unified sensor model. Fully independent of BLE — for sensors the user mounts on
    the bike. Honours per-row invert + trigger_unavailable (tamper); apply_sensor
    handles motion, roles, modes, groups and delays. No-op until one is added."""
    while True:
        try:
            rows = _sensors.get("external") or []
            if not rows or not SUPERVISOR_TOKEN:
                await asyncio.sleep(6)
                continue
            for cfg in rows:
                ent = (cfg.get("entity_id") or "").strip()
                if not ent:
                    continue
                st = await _ha_get("/states/" + ent)
                raw = st.get("state") if isinstance(st, dict) else None
                unavail = raw in (None, "unavailable", "unknown")
                if unavail:
                    active = bool(cfg.get("trigger_unavailable"))
                    _ext_live[ent] = "unavailable"
                else:
                    on = (raw == "on")
                    if cfg.get("invert"):
                        on = not on
                    active = on
                    _ext_live[ent] = raw
                apply_sensor(active, cfg, src_key=_ext_key(cfg), feed_motion=True)
        except Exception as err:  # noqa: BLE001
            log.warning("ext motion loop: %s: %s", type(err).__name__, err)
        await asyncio.sleep(3)


async def alarm_timing_loop() -> None:
    """Promote a 'pending' alarm to 'triggered' once the global entry delay elapses
    (unless disarmed meanwhile). One shared timer; idle when no delay is pending."""
    while True:
        try:
            if _alarm["state"] == "pending":
                delay = int(_sensors.get("entry_delay") or 0)
                if time.time() - _pending_since >= delay:
                    _alarm["fired"] = True
                    _alarm["state"] = "triggered"
                    publish_alarm("triggered")
                    log.info("alarm TRIGGERED by %s (entry delay elapsed)",
                             _pending_reason or "sensor")
        except Exception as err:  # noqa: BLE001
            log.warning("alarm timing loop: %s: %s", type(err).__name__, err)
        await asyncio.sleep(1)


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def pon_cloud_loop() -> None:
    """Additive PON cloud poll (no BLE, no module-battery cost): publish GPS location,
    module charge and speed/in-use from the Connected Bike REST API to HA. Runs only
    when PON_CLIENT_ID + a refresh_token are configured; leaves the BLE path alone."""
    global _pon_refresh
    if not PON_CLIENT_ID or not _pon_refresh:
        return
    st = {"access": None, "exp": 0.0, "bike": PON_BIKE_ID or None}

    async def _refresh(tok: str) -> bool:
        s, js = await _http_json("POST", PON_TOKEN_URL, data={
            "grant_type": "refresh_token", "client_id": PON_CLIENT_ID,
            "refresh_token": tok})
        if s == 200 and js and js.get("access_token"):
            st["access"] = js["access_token"]
            st["exp"] = time.time() + float(js.get("expires_in", 3600))
            rt = js.get("refresh_token") or tok  # Auth0 rotates refresh tokens
            if rt != _pon_refresh:
                globals()["_pon_refresh"] = rt
                _pon_save_refresh(rt)
            return True
        return s  # non-True: the HTTP status (or None) for logging

    async def ensure_token(prefer_option: bool = False) -> bool:
        if not prefer_option and st["access"] and time.time() < st["exp"] - 60:
            return True
        opt = (os.getenv("PON_REFRESH") or "").strip()
        # Normally use the persisted (rotated) token; when the API rejected it,
        # prefer the freshly-configured option token (a re-paste must win over a
        # stale /data/pon.json). Dedup so we never replay the same token.
        order = [opt, _pon_refresh] if prefer_option else [_pon_refresh, opt]
        seen, last = set(), None
        for tok in order:
            tok = (tok or "").strip()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            r = await _refresh(tok)
            if r is True:
                if st.get("tok_fail"):
                    st["tok_fail"] = False
                    log.info("PON token refresh works again")
                return True
            last = r
        # Once per outage, not every poll.
        (log.debug if st.get("tok_fail") else log.warning)(
            "PON token refresh failed (status %s)", last)
        st["tok_fail"] = True
        return False

    # Endpoints PON refuses (403 = the app has no consent for that data), with
    # [retry_at (monotonic), backoff_s]: skipped instead of re-requested (and the
    # token refreshed) every poll. Endpoints with other failures, for quiet logs.
    blocked: dict[str, list] = {}
    failing: set = set()

    def _ep(path: str) -> str:
        """Endpoint key for logs/backoff: no query string, no bike id."""
        p = path.split("?", 1)[0]
        return p.replace(st["bike"], "{bike}") if st["bike"] else p

    async def api(path: str):
        ep = _ep(path)
        blk = blocked.get(ep)
        if blk and time.monotonic() < blk[0]:
            return None
        if not await ensure_token():
            return None
        hdr = {"Authorization": "Bearer " + st["access"], "Accept": "application/json"}
        s, js = await _http_json("GET", PON_BASE + path, headers=hdr)
        if s == 401 or (s == 403 and not blk):
            # Token rejected — retry once with a fresh token, preferring the option
            # token (a re-paste must win over a stale /data/pon.json). A 403 that
            # survives a fresh token is a permission, not a token, problem.
            st["access"] = None
            if await ensure_token(prefer_option=True):
                hdr["Authorization"] = "Bearer " + st["access"]
                s, js = await _http_json("GET", PON_BASE + path, headers=hdr)
        if s == 403:
            backoff = min(blk[1] * 2, 86400.0) if blk else 3600.0
            if not blk:
                log.warning("PON: %s not permitted (403) — the app has no access to "
                            "this data; skipping it (re-checked every few hours)%s", ep,
                            " — riding is detected from GPS movement instead"
                            if "TELEMETRY" in ep else "")
            blocked[ep] = [time.monotonic() + backoff, backoff]
            return None
        if s == 200:
            if blocked.pop(ep, None) is not None or ep in failing:
                log.info("PON: %s available again", ep)
            failing.discard(ep)
            return js
        (log.debug if ep in failing else log.warning)("PON api %s -> status %s", ep, s)
        failing.add(ep)
        return None

    log.info("PON cloud poll starting (every %ss)", int(PON_POLL))
    # Seed the main-battery charge trend from recent cloud history so the inference
    # works right after a restart (the 45-min window otherwise starts empty).
    try:
        if not st["bike"]:
            info = await api("/v1/bikes/info")
            if isinstance(info, list) and info:
                st["bike"] = info[0].get("bikeId")
        if st["bike"]:
            import datetime as _dt

            def _iso(s):
                try:
                    return _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
                except Exception:  # noqa: BLE001
                    return None
            frm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 24 * 3600))
            to = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            hist = await api(f"/v1/bikes/{st['bike']}/IOT/history"
                             f"?from={frm}&to={to}&offset=0&limit=5000")
            items = hist.get("items") if isinstance(hist, dict) else None
            samples = []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    for sub in (it.get("items") or []):
                        if isinstance(sub, dict) and sub.get("chargePercentage") is not None:
                            t = _iso(sub.get("timestamp") or it.get("timestamp"))
                            if t:
                                samples.append((t, sub["chargePercentage"]))
            for t, pct in sorted(samples):
                _record_charge(pct, ts=t)
            if samples:
                log.info("seeded charge trend from %d cloud samples (main battery=%s)",
                         len(samples), _main_battery_state)
    except Exception as err:  # noqa: BLE001
        log.debug("charge seed failed: %s", err)
    while True:
        try:
            if not st["bike"]:
                info = await api("/v1/bikes/info")
                if isinstance(info, list) and info:
                    st["bike"] = info[0].get("bikeId")
            payload: dict = {}
            lk = await api("/v1/bikes/last-known-states")
            entry = None
            if isinstance(lk, list):
                entry = next((b for b in lk if b.get("bikeId") == st["bike"]),
                             lk[0] if lk else None)
            elif isinstance(lk, dict):
                entry = lk
            if entry:
                _log_module_report(entry)
            if entry:
                if entry.get("lastOnline"):
                    payload["last_online"] = entry["lastOnline"]
                loc = (entry.get("location") or {}).get("coordinate") or {}
                if loc.get("latitude") is not None and loc.get("longitude") is not None:
                    payload["latitude"] = loc["latitude"]
                    payload["longitude"] = loc["longitude"]
                    payload["gps_accuracy"] = loc.get("accuracyRadius") or 0
                    # Distance to HA's home zone → reliable home/away (not BLE).
                    home = await _ha_get("/states/zone.home")
                    ha = (home or {}).get("attributes") or {}
                    if ha.get("latitude") is not None and ha.get("longitude") is not None:
                        dist = _haversine(loc["latitude"], loc["longitude"],
                                          ha["latitude"], ha["longitude"])
                        payload["distance_m"] = round(dist)
                        payload["home"] = dist <= float(ha.get("radius", 100) or 100)
                        _cloud_home.update(home=payload["home"], at=time.time())
                iot = entry.get("iotTelemetry") or {}
                if iot.get("moduleCharge") is not None:
                    payload["module_charge"] = iot["moduleCharge"]
                    _record_charge(iot["moduleCharge"])  # cloud charge → battery trend
                if entry.get("odometer") is not None:
                    payload["odometer"] = entry["odometer"]
            if st["bike"]:
                frm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 900))
                to = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                hist = await api(f"/v1/bikes/{st['bike']}/TELEMETRY/history"
                                 f"?from={frm}&to={to}&offset=0&limit=200")
                items = hist.get("items") if isinstance(hist, dict) else None
                if isinstance(items, list):
                    for it in reversed(items):
                        if isinstance(it, dict) and it.get("speedInKmh") is not None:
                            payload["speed"] = it["speedInKmh"]
                            break
            # BLE presence is the authority for home/away (seeing the tracker costs
            # no battery). Cloud home/distance stays pure GPS — only used to show
            # WHERE the bike is when BLE can't see it. Poll cloud slowly when home.
            near_home = _tracker_near()
            moving = False
            if payload:
                speed = _bnum(payload.get("speed"))
                if speed is not None:
                    moving = speed > 0
                    payload["motion_source"] = "speed"
                else:                          # no telemetry: GPS displacement
                    moving = _gps_moving(payload.get("latitude"),
                                         payload.get("longitude"),
                                         payload.get("gps_accuracy"),
                                         near_home=near_home)
                    payload["motion_source"] = "gps"
                payload["in_use"] = moving
                payload["loc_state"] = "moving" if moving else "parked"
                payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _detect_activity(payload, near_home=near_home)  # log transitions
                _last["cloud"] = payload
                if _mqtt is not None:
                    _mqtt.publish(CLOUD_TOPIC, json.dumps(payload), retain=True)
                    _mqtt.publish(CLOUD_STATE_TOPIC, payload["loc_state"], retain=True)
            slow = near_home and not moving
        except Exception as err:  # noqa: BLE001
            log.warning("PON cloud loop: %s", _err_text(err))
            slow = False
        # Poll slowly only while the bike is parked at home; wake early when BLE
        # sees it switch on, arrive or leave (see _cloud_wake).
        try:
            await asyncio.wait_for(_cloud_wake_evt.wait(),
                                   timeout=(MOTION_TEST_POLL if _motion_test
                                            else PON_POLL_ARMED if _presence_guarding()
                                            else PON_POLL_HOME if slow else PON_POLL))
        except asyncio.TimeoutError:
            pass
        _cloud_wake_evt.clear()


async def bosch_cloud_loop() -> None:
    """Additive Bosch SingleKey ID cloud poll (no BLE): battery State-of-Health,
    charge cycles, next-service and last-service straight from Bosch's Data Act API.
    Runs only when a Bosch client_id + refresh_token are configured; PON and BLE are
    left untouched (this is the PRIMARY diagnostic source, PON the GPS/live fallback)."""
    global _bosch_refresh
    if not BOSCH_CLIENT_ID or not _bosch_refresh:
        return
    st = {"access": None, "exp": 0.0, "cap_path": None}

    async def ensure_token() -> bool:
        if st["access"] and time.time() < st["exp"] - 60:
            return True
        # Try the persisted (rotated) token first, then the freshly-configured
        # option token. Each bosch_login.py run mints a new offline session and
        # can revoke older tokens, so a token pasted into the add-on after an
        # earlier one must win over the stale copy on disk.
        seen, cands = [], []
        for tok in (_bosch_refresh, (os.getenv("BOSCH_REFRESH") or "").strip()):
            tok = (tok or "").strip()
            if tok and tok not in seen:
                seen.append(tok)
                cands.append(tok)
        s = None
        for tok in cands:
            s, js = await _http_json("POST", BOSCH_TOKEN_URL, data={
                "grant_type": "refresh_token", "client_id": BOSCH_CLIENT_ID,
                "refresh_token": tok})
            if s == 200 and js and js.get("access_token"):
                st["access"] = js["access_token"]
                st["exp"] = time.time() + float(js.get("expires_in", 3600))
                rt = js.get("refresh_token") or tok  # Keycloak rotates these
                if rt != _bosch_refresh:
                    globals()["_bosch_refresh"] = rt
                    _bosch_save_refresh(rt)
                return True
        log.warning("Bosch token refresh failed (status %s) — re-mint with "
                    "bosch_login.py and update bosch_refresh_token", s)
        return False

    async def api(path: str):
        if not await ensure_token():
            return None
        hdr = {"Authorization": "Bearer " + st["access"], "Accept": "application/json"}
        s, js = await _http_json("GET", BOSCH_API + path, headers=hdr)
        if s == 401:                             # token died early — refresh once
            st["access"] = None
            if await ensure_token():
                hdr["Authorization"] = "Bearer " + st["access"]
                s, js = await _http_json("GET", BOSCH_API + path, headers=hdr)
        return js if s == 200 else None

    log.info("Bosch cloud poll starting (every %ss)", int(BOSCH_POLL))
    while True:
        try:
            payload: dict = {}
            bikes_js = await api(BOSCH_BIKES_EP)
            bikes = (bikes_js.get("bikes") if isinstance(bikes_js, dict) else bikes_js) or []
            # Registry for BLE↔cloud auto-match (all bikes, so multi-bike works).
            globals()["_bosch_registry"] = [{
                "bike_id": b.get("id") or b.get("bikeId"),
                "remote_serial": _norm_serial((b.get("remoteControl") or {}).get(
                    "serialNumber")),
                "name": (b.get("driveUnit") or {}).get("productName"),
            } for b in bikes if isinstance(b, dict)]
            # Prefer the cloud bike whose remote matches the BLE-connected one; the
            # Bosch sensors then follow the actually-present bike (not just the first).
            bike = None
            bm = _bosch_match(_last.get("part_number"))
            if bm:                               # robust to BLE/cloud ordering
                _last["cloud_matched"] = True
                _last["cloud_bike_id"] = bm["bike_id"]
                bike = next((b for b in bikes
                             if (b.get("id") or b.get("bikeId")) == bm["bike_id"]), None)
            if bike is None:
                # With a selected BLE bike, wait for a serial match. First-bike
                # fallback is only valid before any local bike is selected.
                bike = bikes[0] if bikes and not (_bike_addr or _locked_addr or _last.get("part_number")) else None
            if bike:
                bike_id = bike.get("id") or bike.get("bikeId")
                if bike_id:                      # coupling proof for the panel
                    payload["bike_id"] = bike_id
                drive = bike.get("driveUnit") or {}
                batts = bike.get("batteries") or (
                    [bike["battery"]] if isinstance(bike.get("battery"), dict) else [])
                batt = batts[0] if batts else {}
                batt_serial = batt.get("serialNumber")
                batt_part = batt.get("partNumber")

                if drive.get("productName"):
                    payload["drive_unit"] = drive["productName"]
                if batt.get("productName"):
                    payload["battery_model"] = batt["productName"]

                # powerOnTime {'total','withMotorSupport'} in hours — withMotorSupport
                # is the true motor-running time; total is system power-on.
                assist = _nested_num(drive.get("powerOnTime"), "withMotorSupport")
                if assist is not None:
                    payload["motor_hours"] = round(assist, 1)
                total_on = _nested_num(drive.get("powerOnTime"), "total")
                if total_on is not None:
                    payload["power_on_hours"] = round(total_on, 1)

                # chargeCycles {'total','onBike','offBike'} — total is the headline.
                cyc = _nested_num(batt.get("chargeCycles"), "total")
                if cyc is not None:
                    payload["battery_cycles"] = round(cyc, 1)
                lwh = _bnum(batt.get("deliveredWhOverLifetime"))
                if lwh is not None:
                    payload["battery_lifetime_wh"] = round(lwh)

                # serviceDue.odometer and driveUnit.odometer are both in metres →
                # remaining km to the next service.
                due = _bnum((bike.get("serviceDue") or {}).get("odometer"))
                odo = _bnum(drive.get("odometer"))
                if due is not None and odo is not None:
                    payload["next_service_km"] = round((due - odo) / 1000)
                elif due is not None:
                    payload["next_service_km"] = round(due / 1000)

                if bike_id:
                    svc = await api(f"{BOSCH_SERVICE_EP}?bikeId={bike_id}")
                    if svc:
                        payload.update(_parse_service_records(svc, batt_serial))
                    # Auto-name from the cloud brand (e.g. "Urban Arrow") when the
                    # user set no name and the BLE frame lookup didn't resolve one.
                    if payload.get("brand") and bm and not (
                            _cfg0.get("bike_model") or _last.get("product_name")):
                        _last["bike_brand"] = payload["brand"]
                    bp = await api(f"{BOSCH_BIKEPASS_EP}?bikeId={bike_id}")
                    passes = (bp.get("bikePasses") if isinstance(bp, dict) else None) or []
                    if passes:
                        fn = passes[0].get("frameNumber") \
                            or passes[0].get("frameNumberNormalized")
                        if fn:
                            payload["frame_number_bosch"] = fn

                # Diagnosis Field Data (dealer-gated) — capacity tester, path-discovered.
                if batt_part and batt_serial:
                    q = (f"?partNumber={urllib.parse.quote(str(batt_part), safe='')}"
                         f"&serialNumber={urllib.parse.quote(str(batt_serial), safe='')}")
                    order = ([st["cap_path"]] if st["cap_path"] else []) + [
                        c for c in BOSCH_CAPACITY_CANDIDATES if c != st["cap_path"]]
                    for cand in order:
                        cap = await api(cand + q)
                        if cap is not None:
                            st["cap_path"] = cand
                            payload.update(_parse_capacity_tester(cap, batt_serial))
                            break

            if payload:
                payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _last["bosch"] = payload
                if _mqtt is not None:
                    _mqtt.publish(BOSCH_TOPIC, json.dumps(payload), retain=True)
                keys = ", ".join(sorted(payload))
                if keys != st.get("keys"):          # log the field set when it changes
                    st["keys"] = keys
                    log.info("Bosch cloud: %s", keys)
        except Exception as err:  # noqa: BLE001
            log.warning("Bosch cloud loop: %s", _err_text(err))
        await asyncio.sleep(BOSCH_POLL)


async def start_motion(_mqtt_client: mqtt.Client) -> None:
    """Launch the connection-free guard loops. Motion now only comes from
    external HA sensors (BLE motion needed a module-draining connection)."""
    publish_motion(False)
    # No publish_present(False) here: presence_loop restores the last known state
    # and only reports "out of range" after a real grace period of silence.
    _supervise("presence_loop", presence_loop)
    _supervise("proxy_presence_loop", proxy_presence_loop)
    _supervise("ext_motion_loop", ext_motion_loop)
    _supervise("alarm_timing_loop", alarm_timing_loop)


async def motion_test_loop() -> None:
    """DEV (motion_test): log every passive channel that could show movement,
    WITHOUT connecting to anything:
      tracker — our module's full advertisement (active scan, so the scan-response
                too) whenever any field changes, plus rate and RSSI per 10 s;
      hub     — the Bosch hub's advert appearing / disappearing (wake-on-motion);
      cloud   — changed fields of PON's last-known state (_log_module_report).
    Rest, move, rest, and compare the log lines per phase."""
    WINDOW = 10.0
    HUB_GONE_AFTER = 15.0
    arr: dict[str, list] = {}             # address -> [(monotonic ts, rssi)]
    last_sig: dict[str, str] = {}
    hub_seen: dict[str, float] = {}
    hub_on: dict[str, bool] = {}

    def cb(device, adv) -> None:
        kind = _record(device, adv)
        now = time.monotonic()
        rssi = getattr(adv, "rssi", None)
        if kind == "bike":
            hub_seen[device.address] = now
            if not hub_on.get(device.address):
                hub_on[device.address] = True
                log.info("MOTION TEST hub: advert APPEARED [%s @ %sdBm] '%s'",
                         device.address, rssi, device.name or "")
            return
        if kind != "tracker":
            return
        if _tracker_mac and (_tracker_module_mac(adv) or "").upper() != _tracker_mac.upper():
            return                                  # a neighbour's module
        arr.setdefault(device.address, []).append((now, rssi))
        parts = [f"name={adv.local_name!r}", f"tx={getattr(adv, 'tx_power', None)}",
                 f"uuids={sorted(adv.service_uuids or [])}"]
        parts += [f"mfr{cid:04x}={bytes(v).hex()}"
                  for cid, v in sorted((adv.manufacturer_data or {}).items())]
        parts += [f"svc{u[-4:]}={bytes(v).hex()}"
                  for u, v in sorted((adv.service_data or {}).items())]
        sig = " ".join(parts)
        if last_sig.get(device.address) != sig:
            log.info("MOTION TEST tracker: advert %s [%s @ %sdBm]: %s",
                     "CHANGED" if device.address in last_sig else "first",
                     device.address, rssi, sig)
            last_sig[device.address] = sig

    while True:
        if not _motion_test:
            await asyncio.sleep(4)
            continue
        log.info("MOTION TEST started — rest, move the bike, rest; nothing connects")
        try:
            async with _scan_lock, BleakScanner(detection_callback=cb,
                                                scanning_mode="active"):
                while _motion_test:
                    await asyncio.sleep(WINDOW)
                    now = time.monotonic()
                    for addr in list(arr):
                        recent = [(t, r) for t, r in arr[addr] if now - t <= WINDOW]
                        arr[addr] = recent
                        if not recent:
                            log.info("MOTION TEST tracker: [%s] silent for %.0fs",
                                     addr, WINDOW)
                            continue
                        ts = [t for t, _r in recent]
                        gaps = [ts[i] - ts[i - 1] for i in range(1, len(ts))] or [0.0]
                        rs = [r for _t, r in recent if isinstance(r, (int, float))]
                        log.info("MOTION TEST tracker: [%s] %d adverts/%.0fs, gap "
                                 "min/max %.2f/%.2fs, rssi %s..%s", addr, len(recent),
                                 WINDOW, min(gaps), max(gaps),
                                 min(rs) if rs else "?", max(rs) if rs else "?")
                    for addr, on in list(hub_on.items()):
                        if on and now - hub_seen.get(addr, 0) > HUB_GONE_AFTER:
                            hub_on[addr] = False
                            log.info("MOTION TEST hub: advert GONE [%s]", addr)
        except Exception as err:  # noqa: BLE001
            log.warning("motion test scan: %s", _err_text(err))
            await asyncio.sleep(2)


_module_prev: dict = {}


def _flatten(obj, prefix: str = "") -> dict:
    """{'a': {'b': 1}} -> {'a.b': 1}; lists indexed as a.0.b."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = obj
    return out


def _log_module_report(entry: dict) -> None:
    """Log which fields of PON's last-known state changed since the previous poll.
    The module reports on its own when moved (and routinely); these lines are the
    data for telling the two apart before this becomes an alarm source."""
    flat = _flatten(entry)
    changed = {k: v for k, v in flat.items() if _module_prev.get(k) != v}
    gone = sorted(k for k in _module_prev if k not in flat)
    armed = "armed" if _presence_guarding() else "disarmed"
    if not _module_prev:
        log.info("PON module report: baseline (%s) %s", armed,
                 json.dumps(flat, default=str))
    elif changed or gone:
        log.info("PON module report: changed (%s) %s%s", armed,
                 json.dumps(changed, default=str), f" gone {gone}" if gone else "")
    elif _motion_test:
        log.info("PON module report: unchanged")
    _module_prev.clear()
    _module_prev.update(flat)


# ------------------------------------------------------------- setup UI (Ingress)


async def _ui_status(_request):
    if _insights is not None:
        snapshot = _insights.snapshot()
        snapshot["receiver_health"] = "unavailable" if _receiver_fault and time.time() - _proxy_alive_at > 30 else "ok"
        _last["insights"] = snapshot
    return web.json_response({"bike": _bike_addr, "locked": _locked_addr,
                              "tracker": _tracker_mac, "tracker_off": _tracker_off,
                              "alarm_off": _alarm_off,
                              "show_maintenance": _show_maintenance,
                              "motion_test": _motion_test,
                              "bike_off": _bike_off,
                              "presence_alarm": _presence_alarm,
                              "alarm_grace_s": int(PRESENCE_ALARM_GRACE),
                              "presence_mode": _pres["mode"],
                              "ble_proxy": bool(_PROXY_HOST and _PROXY_KEY),
                              "device": {"manufacturer": DEVICE["manufacturer"],
                                         "model": DEVICE["model"]},
                              "last": _last})


async def _ui_remove_bike(_request):
    """Forget the bike: clear the stored selection + all display/persisted data and
    pause reading until a bike is (re-)added via the Settings tab."""
    global _bike_addr, _locked_addr, _bike_off
    _bike_off = True
    _bike_addr = None
    _locked_addr = None
    _clear_bike_readings()
    _save_cfg()
    if _mqtt is not None:                       # clear the retained sensor values
        _mqtt.publish(STATE_TOPIC, "", retain=True)
    log.info("UI: bike removed — reading paused until re-added")
    return web.json_response({"ok": True})


async def _ui_preferences(request):
    global _show_maintenance
    data = await request.json()
    if not isinstance(data, dict) or type(data.get("show_maintenance")) is not bool:
        return web.json_response({"ok": False}, status=400)
    _show_maintenance = data["show_maintenance"]
    _save_cfg()
    return web.json_response({"ok": True, "show_maintenance": _show_maintenance})


async def _ui_set_alarm(request):
    global _alarm_off
    data = await request.json()
    _alarm_off = not bool(data.get("on", True))
    _save_cfg()
    if _mqtt is not None:
        publish_alarm_discovery(_mqtt)        # add or remove the HomeKit accessory
        if _alarm_off:
            _alarm.update(state="disarmed", fired=False)
            publish_alarm("disarmed")
    log.info("UI: alarm %s", "off" if _alarm_off else "on")
    return web.json_response({"ok": True, "alarm_off": _alarm_off})


async def _ui_alarm(request):
    data = await request.json()
    new = {"DISARM": "disarmed", "ARM_AWAY": "armed_away",
           "ARM_HOME": "armed_home"}.get((data.get("cmd") or "").upper())
    if not new:
        return web.json_response({"ok": False}, status=400)
    _alarm["restored"] = True            # a user action wins over a late retained state
    _alarm["state"] = new
    _alarm["fired"] = False
    if new in ARMED_STATES:
        _note_armed()            # start the exit-delay window
    publish_alarm(new)
    return web.json_response({"ok": True, "state": new})


async def _ui_refresh_tracker(_request):
    _spawn(read_tracker_battery(proactive=False), "tracker_refresh")  # single-flighted
    return web.json_response({"ok": True})


async def _ui_scan(_request):
    try:
        async with _scan_lock, BleakScanner(detection_callback=_record):
            await asyncio.sleep(8)
    except Exception as err:  # noqa: BLE001
        return web.json_response({"error": str(err)}, status=500)
    fresh = [d for d in _discovered.values() if time.time() - d["ts"] < 90]
    fresh.sort(key=lambda d: d["rssi"], reverse=True)
    return web.json_response(fresh)


async def _read_ble_serial(address: str) -> "str | None":
    """Connect briefly to a scanned device and read its DIS 0x2a25 serial (the
    BRC3600 remote serial we match against the cloud). Best-effort, short timeout."""
    try:
        async with _scan_lock, BleakClient(address, timeout=15.0) as client:
            raw = await asyncio.wait_for(
                client.read_gatt_char(DEVICE_INFO_CHARS["serial"]), timeout=8)
            return bytes(raw).decode(errors="ignore").strip() or None
    except Exception as err:  # noqa: BLE001
        log.debug("identify %s: %s", address, err)
        return None


async def _ui_identify(request):
    """Connect to a scanned bike, read its serial, and report whether it matches a
    registered Bosch cloud bike — for onboarding auto-select + auto-name. Only worth
    a connect when the Bosch cloud registry is populated."""
    if not _bosch_registry:
        return web.json_response({"matched": False, "registry": False})
    data = await request.json()
    addr = (data.get("address") or "").strip()
    if not addr:
        return web.json_response({"matched": False})
    serial = await _read_ble_serial(addr)
    m = _bosch_match(serial) if serial else None
    return web.json_response({"matched": bool(m), "registry": True,
                              "bike_id": m["bike_id"] if m else None,
                              "name": (m.get("name") if m else None)})


async def _ui_select_bike(request):
    global _bike_addr, _locked_addr, _bike_off
    data = await request.json()
    address = (data.get("address") or "").strip() or None
    if address and not re.fullmatch(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}", address):
        return web.json_response({"ok": False, "error": "invalid Bluetooth address"}, status=400)
    if (address or "").upper() != (_bike_addr or _locked_addr or "").upper():
        _clear_bike_readings()
    _bike_addr = address
    _locked_addr = None
    _bike_off = False                 # (re-)adding a bike resumes reading
    name = (data.get("name") or "").strip()
    if name and not _cfg0.get("bike_model"):
        _last["bike_brand"] = name    # auto-name from the Bosch cloud match
    _save_cfg()
    log.info("UI: bike set to %s%s", _bike_addr, f" ({name})" if name else "")
    return web.json_response({"ok": True, "bike": _bike_addr})


async def _ui_pair(_request):
    if not _bike_addr:
        return web.json_response({"ok": False, "error": "no bike selected"}, status=400)
    ok = await ensure_bonded(_bike_addr)
    _last["bonded"] = ok
    return web.json_response({"ok": bool(ok)})


async def _ui_select_tracker(request):
    global _tracker_mac, _tracker_off
    data = await request.json()
    _tracker_off = bool(data.get("off", False))
    _tracker_mac = None if _tracker_off else ((data.get("module_mac") or "").strip() or None)
    _save_cfg()
    log.info("UI: tracker set to %s (off=%s)", _tracker_mac, _tracker_off)
    return web.json_response({"ok": True, "tracker": _tracker_mac, "off": _tracker_off})


async def _ui_sensors(_request):
    """Full sensor registry + candidate HA entities + live per-source state, for
    the Sensoren card."""
    live = {
        "presence": {"present": bool(_last.get("tracker_present", True))},
        "external": dict(_ext_live),
    }
    return web.json_response({"available": bool(SUPERVISOR_TOKEN),
                              "sensors": _sensors,
                              "entities": await list_ha_motion_entities(),
                              "live": live})


def _clean_row(src: dict, *, ext: bool) -> dict:
    """Normalise one sensor row from the UI to the trusted shape."""
    row = _sensor_row()
    row["enabled"] = bool(src.get("enabled", True))
    row["role"] = "motion" if src.get("role") == "motion" else "alarm"
    row["always_on"] = bool(src.get("always_on"))
    modes = [m for m in (src.get("modes") or []) if m in ARMED_STATES]
    row["modes"] = modes or list(ARMED_STATES)
    if ext:
        row["entity_id"] = (src.get("entity_id") or "").strip()
        row["name"] = (src.get("name") or row["entity_id"]).strip()
        row["trigger_unavailable"] = bool(src.get("trigger_unavailable"))
        row["invert"] = bool(src.get("invert"))
        row["group"] = (src.get("group") or "").strip()
        row["id"] = (src.get("id") or "").strip()
    else:   # built-in rows have no entity/invert/unavailable/group
        for k in ("invert", "trigger_unavailable", "group"):
            row.pop(k, None)
    return row


async def _ui_set_sensors(request):
    """Validate + persist the whole sensor registry, then reconcile live motion."""
    global _sensors
    data = await request.json()
    inc = data.get("sensors") if isinstance(data.get("sensors"), dict) else data
    b = inc.get("builtin") or {}
    clean = {
        "builtin": {
            "presence": _clean_row(b.get("presence") or {}, ext=False),
        },
        "external": [],
        "groups": {},
        "entry_delay": max(0, int(inc.get("entry_delay") or 0)),
        "exit_delay": max(0, int(inc.get("exit_delay") or 0)),
    }
    used: set = set()
    for i, r in enumerate(inc.get("external") or []):
        row = _clean_row(r, ext=True)
        if not row["entity_id"]:
            continue
        rid = row["id"] or f"ext{i + 1}"
        while rid in used:
            rid += "_"
        row["id"] = rid
        used.add(rid)
        clean["external"].append(row)
    groups_in = inc.get("groups") or {}
    for gid in {r["group"] for r in clean["external"] if r.get("group")}:
        g = groups_in.get(gid) or {}
        clean["groups"][gid] = {"min_active": max(2, int(g.get("min_active") or 2)),
                                "window": max(1, int(g.get("window") or 30))}
    _sensors = clean
    _save_cfg()
    # Drop live motion from sources that no longer exist or were disabled.
    valid = {"presence"} | {_ext_key(r) for r in clean["external"]}
    for k in list(_motion_src):
        if k not in valid:
            _motion_src.pop(k, None)
            _src_off_since.pop(k, None)
    _publish_motion_or()
    log.info("UI: sensors updated (%d external)", len(clean["external"]))
    return web.json_response({"ok": True})


_tile_cache: dict = {}


async def _ui_tile(request):
    """Proxy OpenStreetMap map tiles through the add-on (same origin) so they aren't
    blocked by Home Assistant's ingress CSP. Keyless (CARTO now needs an API key).
    OSM requires a real User-Agent or it 403s. Small in-memory cache."""
    z = request.match_info["z"]
    x = request.match_info["x"]
    y = request.match_info["y"].split(".")[0]
    if not (z.isdigit() and x.isdigit() and y.isdigit()):
        return web.Response(status=400)
    key = f"{z}/{x}/{y}"
    hdr = {"Cache-Control": "max-age=86400"}
    if key in _tile_cache:
        return web.Response(body=_tile_cache[key], content_type="image/png", headers=hdr)
    if aiohttp is None:
        return web.Response(status=503)
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    ua = {"User-Agent": "cargobike-ebike-ha (Home Assistant add-on; "
          "https://github.com/bramboe/cargobike-ebike-ha)"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=ua,
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return web.Response(status=r.status)
                data = await r.read()
        if len(_tile_cache) < 800:
            _tile_cache[key] = data
        return web.Response(body=data, content_type="image/png", headers=hdr)
    except Exception as err:  # noqa: BLE001
        log.debug("tile proxy %s: %s", key, err)
        return web.Response(status=502)


# Home Assistant's ingress gateway (Supervisor) — the only legitimate client. The
# UI has no login of its own, so without this check any other add-on container on
# the internal network could arm/disarm the alarm or remove the bike.
INGRESS_PEERS = frozenset({"172.30.32.2", "127.0.0.1", "::1"})


def _peer_allowed(remote: "str | None") -> bool:
    if not remote:
        return False
    if remote.startswith("::ffff:"):             # IPv4-mapped IPv6
        remote = remote[7:]
    return remote in INGRESS_PEERS


_refused_peers: set = set()

if web is not None:
    @web.middleware
    async def _ingress_only(request, handler):
        if not _peer_allowed(request.remote):
            if request.remote not in _refused_peers:     # once per client
                _refused_peers.add(request.remote)
                log.warning("UI: refused request from %s (not the HA ingress)",
                            request.remote)
            return web.Response(status=403, text="Use the panel in Home Assistant.")
        return await handler(request)


def make_app() -> "web.Application":
    """The ingress panel + its JSON API."""
    app = web.Application(middlewares=[_ingress_only])
    async def index(_request):
        return web.Response(text=INDEX_HTML, content_type="text/html")

    def static(path: str):
        async def handler(_request):
            return web.FileResponse(path)
        return handler

    app.add_routes([
        web.get("/", index),
        web.get("/bike.png", static("/bike.png")),
        web.get("/leaflet.js", static("/leaflet.js")),
        web.get("/leaflet.css", static("/leaflet.css")),
        web.get("/tile/{z}/{x}/{y}", _ui_tile),
        web.get("/api/status", _ui_status),
        web.post("/api/preferences", _ui_preferences),
        web.post("/api/scan", _ui_scan),
        web.post("/api/identify", _ui_identify),
        web.post("/api/select_bike", _ui_select_bike),
        web.post("/api/remove_bike", _ui_remove_bike),
        web.post("/api/pair", _ui_pair),
        web.post("/api/select_tracker", _ui_select_tracker),
        web.post("/api/set_alarm", _ui_set_alarm),
        web.post("/api/alarm", _ui_alarm),
        web.post("/api/refresh_tracker", _ui_refresh_tracker),
        web.get("/api/sensors", _ui_sensors),
        web.post("/api/sensors", _ui_set_sensors),
    ])
    return app


async def start_web() -> None:
    if web is None:
        log.warning("setup UI unavailable (aiohttp missing)")
        return
    runner = web.AppRunner(make_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", INGRESS_PORT).start()
    log.info("setup UI listening on :%s", INGRESS_PORT)


async def _persist_last_loop() -> None:
    """Periodically snapshot _last to disk so a restart shows data instantly."""
    while True:
        await asyncio.sleep(20)
        _save_last()
        _charge_save()
        _publish_insights()


async def main() -> None:
    global _mqtt, _loop
    _loop = asyncio.get_running_loop()
    _ensure_insights()
    _restore_local_alarm()
    _load_last()        # seed the panel from disk before the UI serves /api/status
    _charge_load()      # restore module-charge trend so main-battery survives restarts
    _mqtt = make_mqtt()
    log.info("reader v2.0 started (%s, cooldown %ss)",
             _bike_addr or "auto-detect", COOLDOWN)
    publish_status("Starting…", "OFF")
    try:
        await start_web()
    except Exception as err:  # noqa: BLE001 - UI must never block the reader
        log.warning("setup UI failed to start: %s", err)
    # Restore the alarm from the broker's retained state before the sensors can act
    # on it (defaults to disarmed on a first-ever run). If the broker isn't up yet,
    # start anyway: the restore completes in the background once it connects.
    restore = _spawn(_alarm_restore(), "alarm_restore")
    try:
        await asyncio.wait_for(asyncio.shield(restore), timeout=30)
    except asyncio.TimeoutError:
        log.warning("MQTT broker %s:%s not reachable yet — starting anyway, "
                    "connecting in the background", MQTT_HOST, MQTT_PORT)
    await start_motion(_mqtt)
    # One-time tracker battery read at startup so the module % is always shown
    # (it then refreshes when the bike is on or the alarm is armed, idle otherwise).
    _spawn(read_tracker_battery(), "tracker_battery_startup")
    _supervise("persist_last", _persist_last_loop)   # keep the on-disk snapshot fresh
    _supervise("motion_test", motion_test_loop)  # dev: passive motion channels test
    _supervise("pon_cloud", pon_cloud_loop)      # additive cloud poll (no BLE)
    _supervise("bosch_cloud", bosch_cloud_loop)  # additive Bosch health/service poll
    try:
        await _run_forever("ble_loop", lambda: ble_loop(_mqtt))
    finally:
        if _insights is not None:
            try:
                _insights.save(force=True)
            except OSError:
                pass
        _mqtt.publish(READER_AVAILABILITY_TOPIC, "offline", retain=True)
        _mqtt.disconnect()
        _mqtt.loop_stop()


if __name__ == "__main__":
    asyncio.run(main())

