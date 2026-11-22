"""Derived data is never fabricated from USB, stale history or another bike."""
import asyncio
import json
from pathlib import Path

import pytest

from alarm_state import restore_state
from diagnostics import ALLOWED_ADDRESSES, decode, read_frame, response
from history import DAY, RideHistory
from insights import Insights


def test_signed_temperatures_and_real_capture_scaling():
    assert decode(0x008B, bytes.fromhex("08ea01"))["value"] == 11.7
    assert decode(0x008B, bytes.fromhex("0813"))["value"] == -1
    assert decode(0x0088, bytes.fromhex("082b"))["value"] == 43
    assert decode(0x0096, bytes.fromhex("08dc04"))["value"] == 60.4
    assert decode(0x00D8, bytes.fromhex("085e"))["value"] == 94
    assert decode(0x00D8, bytes.fromhex("08ff01")) is None
    assert decode(0x2185, b"") is None  # missing service target is not due now
    with pytest.raises(ValueError):
        decode(0x008B, b"\x08\x80")


def test_frames_only_request_allowlisted_reads_and_match_peer():
    for address in ALLOWED_ADDRESSES:
        for seq in range(32):
            f = read_frame(address, seq)
            assert f[:4] == bytes.fromhex("30054180")
            assert f[-1] < 16  # READ type; never WRITE/RPC/SUBSCRIBE
    with pytest.raises(ValueError):
        read_frame(0xFFFF, 0)
    good = bytes.fromhex("300800d8c18010085e00")[:9]
    # A short, implicit-success response from battery SoH to BLE host 4180.
    good = bytes.fromhex("300700d8c18010085e")
    assert response(good, 0xD8, 0) == (0, bytes.fromhex("085e"))
    assert response(good, 0xD8, 1) is None
    assert response(good.replace(bytes.fromhex("c180"), bytes.fromhex("8e10")), 0xD8, 0) is None


def test_pending_alarm_survives_restart_and_unknown_is_not_disarm():
    assert restore_state("pending") == "triggered"
    assert restore_state("armed_away") == "armed_away"
    assert restore_state("garbage") is None


def history_with_daily_rides(days=14):
    h = RideHistory()
    km = 1000
    for day in range(days + 1):
        t = (day + 1) * DAY
        h.observe(km, 80, at=t, identity="bike")
        km += 10
        h.observe(km, 75, at=t + 1800, identity="bike")
        h.observe(km, 75, at=t + 3600, identity="bike")
    return h, (days + 1) * DAY + 3600


def test_forecast_uses_calendar_frequency_not_just_ride_length():
    h, now = history_with_daily_rides()
    s = h.summary(200, now=now)
    assert s["forecast_status"] == "estimated"
    assert s["km_per_ride"] == 10
    assert 18 <= s["service_days"] <= 21
    assert s["service_weeks"] == round(s["service_days"] / 7, 1)
    assert s["service_rides"] == 20
    # Same ride lengths, every other day: twice as long to service.
    for row in h.samples:
        row["at"] *= 2
    for row in h.rides:
        row["start"] *= 2
        row["end"] *= 2
    slower = h.summary(200, now=now * 2)
    assert slower["service_days"] > s["service_days"] * 1.8


def test_forecast_requires_history_and_rejects_stale_and_zero_use():
    h = RideHistory()
    assert h.summary(100, now=DAY)["service_days"] is None
    h, now = history_with_daily_rides(3)
    assert h.summary(100, now=now)["service_days"] is None
    h, now = history_with_daily_rides()
    assert h.summary(100, now=now + 8 * DAY)["forecast_status"] == "stale_history"
    assert h.summary(-1, now=now)["service_days"] == 0
    assert h.summary(None, now=now)["forecast_status"] == "no_service_target"


def test_history_rejects_reset_outlier_and_out_of_order():
    h = RideHistory()
    assert h.observe(100, 90, at=DAY, identity="A")
    assert not h.observe(10, 80, at=DAY + 1, identity="A")
    assert not h.observe(10000, 80, at=DAY + 1, identity="A")
    assert not h.observe(101, 80, at=DAY - 1, identity="A")
    assert h.observe(5, 80, at=2 * DAY, identity="B")
    assert len(h.samples) == 1
    assert h.rides == []


def test_charging_and_long_gaps_do_not_create_fake_consumption():
    h = RideHistory()
    h.observe(100, 80, at=DAY)
    h.observe(110, 70, at=DAY + 1800)
    h.observe(110, 90, at=DAY + 1900)  # charging while stationary
    h.observe(111, 85, at=DAY + 2000)
    h.finish()
    assert h.rides[-1]["battery_drop"] is None
    h.observe(130, 60, at=2 * DAY)
    h.finish()
    assert h.rides[-1]["quality"] == "interval"
    assert h.rides[-1]["battery_pct_per_km"] is None


def test_insights_persist_and_use_field_level_freshness(tmp_path):
    path = str(tmp_path / "insights.json")
    i = Insights(path)
    i.observe({"odometer": 100, "battery": 80, "next_service": 200}, identity="A", now=DAY)
    i.enrich({"source": "ble", "measured_at": DAY, "values": {"battery_soh": 94, "battery_voltage": 37.2},
              "capabilities": {"00d8": "available", "008c": "available"}, "components": {}})
    i.save(force=True)
    restored = Insights(path)
    assert restored.snapshot(now=DAY + 30)["local_battery_soh"] == 94
    assert restored.snapshot(now=2 * DAY + 1)["local_battery_soh"] is None
    with pytest.raises(ValueError):
        i.enrich({"source": "usb"})
    i.enrich({"source": "ble", "measured_at": DAY + 60, "values": {}, "capabilities": {"00d8": "denied"}})
    assert i.snapshot(now=DAY + 60)["local_battery_soh"] is None
    assert i.snapshot(now=DAY + 60)["readings"]["battery_soh"]["status"] == "denied"


def test_temperature_warning_and_component_replacement(tmp_path):
    i = Insights(str(tmp_path / "i.json"))
    i.enrich({"source": "ble", "measured_at": DAY, "values": {"battery_temperature": 55},
              "capabilities": {"008b": "available"}, "components": {"battery": {"serial": "A"}}})
    assert i.snapshot(now=DAY)["battery_temperature_warning"] is True
    i.enrich({"source": "ble", "measured_at": DAY + 1, "values": {}, "capabilities": {},
              "components": {"battery": {"serial": "B"}}})
    assert i.snapshot(now=DAY + 1).get("local_battery_temperature") is None
    assert i.changes[-1]["change"] == "replaced"


def test_existing_entity_identifiers_and_topics_are_preserved(r, fake_mqtt):
    r.PON_CLIENT_ID = ""
    r._publish_discovery(fake_mqtt)
    old = json.loads((Path(__file__).parent / "fixtures" / "legacy_discovery.json").read_text())
    actual = {topic: json.loads(payload) for topic, payload, _ in fake_mqtt.published if payload}
    for entry in old:
        cfg = actual[entry["topic"]]
        for key in ("unique_id", "state_topic", "command_topic"):
            assert cfg.get(key) == entry[key]


def test_alarm_restore_from_disk_and_retained_pending(r, fake_mqtt):
    r._write_json_atomic(r.ALARM_FILE, {"state": "pending"})
    r._restore_local_alarm()
    assert r._alarm["state"] == "triggered"
    assert r._alarm["fired"] is True
    r._alarm.update(state="disarmed", restored=False, fired=False)
    r._handle_mqtt_message(r.ALARM_STATE_TOPIC, "pending")
    assert r._alarm["state"] == "triggered"


def test_ble_reader_reassembles_split_notifications_and_caches_denied():
    from ble_diagnostics import DiagnosticReader

    async def run():
        reader = DiagnosticReader()
        calls = []

        class Client:
            async def write_gatt_char(self, _char, frame, **_kw):
                calls.append(frame)
                address = ((frame[4] & 127) << 8) | frame[5]
                # Explicit DENIED status, echoed sequence and destination.
                raw = bytes((48, 6, address >> 8, address & 255, 65, 128, 16 | frame[-1], 6))
                reader.feed(raw[:3])
                reader.feed(raw[3:])

        first = await reader.collect(Client(), "write", budget=10)
        assert set(first["capabilities"].values()) == {"denied"}
        assert first["values"] == {}
        before = len(calls)
        await reader.collect(Client(), "write", budget=10)
        assert len(calls) == before
    asyncio.run(run())


def test_precision_and_firmware_20_are_preserved_in_legacy_decoder(r):
    # battery=43; odometer=3,302,068 m; service target=3,479,961 m.
    def vi(v):
        b = bytearray()
        while v > 127:
            b.append((v & 127) | 128)
            v >>= 7
        return bytes(b) + bytes([v])
    target = bytes([16]) + vi(3479961)
    raw = bytes([80, 43, 96]) + vi(3302068) + bytes([162, 1, len(target)]) + target
    state = r.parse_eb21(raw)
    assert state["odometer"] == 3302.068
    assert state["next_service"] == 177.893
    text = b"20.27.0"
    body = bytes.fromhex("1806c080100a") + bytes([len(text)]) + text
    assert r.parse_components(bytes([48, len(body)]) + body)["drive"]["firmware"] == "20.27.0"


def test_service_attribute_uses_absolute_odometer_not_remaining():
    # protobuf field 2 with the absolute service target, not field 1/date.
    assert decode(0x2185, bytes.fromhex("10e807"))["value"] == 1


def test_unknown_and_empty_fields_never_forge_voltage_zero():
    assert decode(0x008C, b"") is None
    assert decode(0xFFFF, b"\x08\x01") is None


def test_bike_selection_clears_caches_retained_values_and_history(r, fake_mqtt, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(r, "_bike_addr", "AA:AA:AA:AA:AA:AA")
    monkeypatch.setattr(r, "_locked_addr", None)
    r._ensure_insights().observe({"odometer": 100, "battery": 70}, identity="A", now=DAY)
    r._last.update(device_info={"serial": "old"}, frame_number="old", battery=70, alarm="armed_home")
    async def data():
        return {"address": "BB:BB:BB:BB:BB:BB"}
    response = asyncio.run(r._ui_select_bike(SimpleNamespace(json=data)))
    assert response.status == 200
    assert "device_info" not in r._last and "frame_number" not in r._last
    assert r._last["alarm"] == "armed_home"
    assert r._insights.history.samples == []
    assert fake_mqtt.topic(r.STATE_TOPIC)[-1] == ""
    assert fake_mqtt.topic(r.MODE_TOPIC)[-1] == ""
    assert fake_mqtt.topic(r.RANGE_TOPIC)[-1] == ""
    assert r._bike_generation == 1


def test_cloud_measurement_for_another_battery_does_not_leak(r):
    js = {"serviceRecords": [{"type": "BATTERY_MEASUREMENT", "attributes": {
        "createdAt": "2026-11-22", "battery": {"serialNumber": "OTHER"},
        "measuredCapacityPercentage": 99}}]}
    assert "battery_soh" not in r._parse_service_records(js, "OUR_BATTERY")


def test_high_frequency_parked_observations_are_bounded():
    h = RideHistory()
    for t in range(0, 7 * DAY, 120):
        h.observe(100, 50, at=t)
    assert len(h.samples) <= 169


def test_service_target_keeps_counting_when_optional_field_is_missing(tmp_path):
    i = Insights(str(tmp_path / "i.json"))
    i.observe({"odometer": 100, "next_service": 200}, identity="A", now=DAY)
    i.observe({"odometer": 110}, identity="A", now=DAY + 3600)
    assert i.snapshot(now=DAY + 3600)["service_remaining_km"] == 190
    i.save(force=True)
    i = Insights(str(tmp_path / "i.json"))
    i.observe({"odometer": 120}, identity="A", now=DAY + 7200)
    assert i.remaining == 180


def test_new_pack_measurements_are_not_erased_with_old_pack(tmp_path):
    i = Insights(str(tmp_path / "i.json"))
    for serial, soh, at in (("A", 70, DAY), ("B", 100, DAY + 1)):
        i.enrich({"source": "ble", "measured_at": at, "values": {"battery_soh": soh},
                  "capabilities": {"00d8": "available"}, "components": {"battery": {"serial": serial}}})
    assert i.snapshot(now=DAY + 1)["local_battery_soh"] == 100


def test_runtime_has_no_usb_dependency_and_does_not_seed_captured_values():
    source = (Path(__file__).parents[1] / "ebike_battery" / "bosch_mqtt_reader.py").read_text()
    assert "import usb" not in source
    assert "urban-arrow-usb-scan" not in source
    assert "snapshot" in source


def test_main_notify_callback_feeds_diagnostics_once(r, monkeypatch):
    calls = []
    class Reader:
        def feed(self, raw):
            calls.append(raw)
        async def collect(self, *args):
            return {"source": "ble", "measured_at": DAY, "values": {}, "capabilities": {}}
    class Client:
        async def start_notify(self, char, cb):
            cb(char, bytearray.fromhex("30029809"))
        async def write_gatt_char(self, *args, **kwargs):
            pass
        async def stop_notify(self, *args):
            pass
    async def no_sleep(*args):
        pass
    monkeypatch.setattr(r, "_ble_diagnostics", Reader())
    monkeypatch.setattr(r, "_DIAGNOSTICS_ENABLED", True)
    monkeypatch.setattr(r, "_COMP_INIT", [])
    monkeypatch.setattr(r.asyncio, "sleep", no_sleep)
    r._ensure_insights()
    asyncio.run(r.read_push(Client()))
    assert calls == [bytes.fromhex("30029809")]


def test_retained_reading_for_old_bike_does_not_repopulate_selection(r, monkeypatch):
    monkeypatch.setattr(r, "_bike_addr", "BB:BB:BB:BB:BB:BB")
    r._handle_mqtt_message(r.STATE_TOPIC, json.dumps({"address": "AA:AA:AA:AA:AA:AA", "battery": 50}))
    r._handle_mqtt_message(r.MODE_TOPIC, json.dumps({"mode": "Turbo"}))
    r._handle_mqtt_message(r.RANGE_TOPIC, json.dumps({"eco": 90}))
    assert r._last == {}
    r._handle_mqtt_message(r.STATE_TOPIC, json.dumps({"address": "BB:BB:BB:BB:BB:BB", "battery": 80}))
    assert r._last["battery"] == 80
