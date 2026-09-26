"""Shared fixtures: import the add-on's reader module with its state isolated."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import threading

import pytest

ADDON = pathlib.Path(__file__).resolve().parents[1] / "ebike_battery"
sys.path.insert(0, str(ADDON))

import bosch_mqtt_reader as reader  # noqa: E402


class FakeMqtt:
    """Records publishes; stands in for the paho client."""

    def __init__(self) -> None:
        self.published: list[tuple[str, object, bool]] = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, *_args, **_kwargs):
        return (0, 1)

    def topic(self, topic: str) -> list:
        return [p for t, p, _r in self.published if t == topic]


@pytest.fixture
def r(monkeypatch, tmp_path):
    """The reader module with files in tmp_path and all mutable state reset."""
    for name in ("DATA_FILE", "LAST_FILE", "PON_FILE", "BOSCH_FILE",
                 "ACTIVITY_FILE", "_CHARGE_FILE"):
        monkeypatch.setattr(reader, name, str(tmp_path / f"{name.lower()}.json"))
    monkeypatch.setattr(reader, "_mqtt", None)
    monkeypatch.setattr(reader, "_mqtt_up", threading.Event())
    monkeypatch.setattr(reader, "_alarm",
                        {"state": "disarmed", "restored": False, "fired": False})
    monkeypatch.setattr(reader, "_last", {})
    monkeypatch.setattr(reader, "_activity_log", [])
    monkeypatch.setattr(reader, "_pon_prev", {})
    monkeypatch.setattr(reader, "_gps_track",
                        {"lat": None, "lon": None, "moving": False, "still": 0})
    monkeypatch.setattr(reader, "_tracker_seen_ts", 0.0)
    monkeypatch.setattr(reader, "_charge_hist", [])
    monkeypatch.setattr(reader, "_cloud_wake_ts", -1e9)
    # asyncio primitives bind to the first loop that uses them: fresh per test.
    monkeypatch.setattr(reader, "_cloud_wake_evt", asyncio.Event())
    monkeypatch.setattr(reader, "_scan_lock", asyncio.Lock())
    monkeypatch.setattr(reader, "_tracker_read_lock", asyncio.Lock())
    monkeypatch.setattr(reader, "_tasks", set())
    monkeypatch.setattr(reader, "_loop", None)
    return reader


@pytest.fixture
def fake_mqtt(r, monkeypatch) -> FakeMqtt:
    fake = FakeMqtt()
    monkeypatch.setattr(r, "_mqtt", fake)
    return fake
