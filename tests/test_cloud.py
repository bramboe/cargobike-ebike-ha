"""PON cloud poll: ride detection without telemetry, and 403 handling."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

HOME = (52.0, 5.0)


def north(metres: float) -> tuple[float, float]:
    return (HOME[0] + metres / 111_195.0, HOME[1])


# --------------------------------------------------------------- GPS fallback


def test_first_fix_is_only_a_baseline(r):
    assert r._gps_moving(*HOME) is False


def test_ride_with_a_red_light_and_a_stop(r):
    track = [HOME, HOME, north(400), north(900), north(900),   # red light
             north(1400), north(1400), north(1400)]           # parked
    got = [r._gps_moving(*p) for p in track]
    assert got == [False, False, True, True, True, True, True, False]


def test_parked_at_once_when_heard_at_home(r):
    r._gps_moving(*HOME)
    assert r._gps_moving(*north(500)) is True
    assert r._gps_moving(*north(520), near_home=True) is False


def test_gps_jump_heard_at_home_is_not_a_ride(r):
    r._gps_moving(*HOME)
    assert r._gps_moving(*north(300), near_home=True) is False


def test_jitter_within_reported_accuracy_is_not_riding(r):
    r._gps_moving(*HOME)
    assert r._gps_moving(*north(120), accuracy=80) is False
    assert r._gps_moving(*north(450), accuracy=80) is True


def test_missing_fix_keeps_the_last_state(r):
    r._gps_moving(*HOME)
    r._gps_moving(*north(500))
    assert r._gps_moving(None, None) is True


# ----------------------------------------------------------- activity events


def _types(r) -> list[str]:
    return [e["type"] for e in r._activity_log]


def _snap(point, loc_state, home):
    return {"latitude": point[0], "longitude": point[1],
            "loc_state": loc_state, "home": home}


def test_displacement_while_parked_is_logged_as_moved(r):
    r._detect_activity(_snap(HOME, "parked", True))
    r._detect_activity(_snap(north(60), "parked", True))
    r._detect_activity(_snap(north(300), "parked", False))
    assert _types(r) == ["left_home", "moved"]


def test_no_moved_when_heard_at_home_or_right_after_a_ride(r):
    r._detect_activity(_snap(HOME, "parked", True))
    r._detect_activity(_snap(north(300), "parked", True), near_home=True)
    r._detect_activity(_snap(north(900), "moving", False))
    r._detect_activity(_snap(north(1400), "parked", False))
    assert _types(r) == ["ride_start", "left_home", "ride_stop"]


# ------------------------------------------------------ pon_cloud_loop (fake)


class FakePon:
    """Scripted PON: token endpoint, bike info, last-known-states walking a track,
    and a TELEMETRY history that always answers 403 (no consent)."""

    def __init__(self, track):
        self.track = list(track)
        self.polls = 0
        self.token_calls = 0
        self.telemetry_calls = 0

    async def http_json(self, method, url, *, headers=None, data=None):
        if method == "POST":
            self.token_calls += 1
            return 200, {"access_token": f"at{self.token_calls}", "expires_in": 3600,
                         "refresh_token": data["refresh_token"]}
        if url.endswith("/v1/bikes/info"):
            return 200, [{"bikeId": "BIKE1"}]
        if "/IOT/history" in url:
            return 200, {"items": []}
        if url.endswith("/v1/bikes/last-known-states"):
            lat, lon = self.track[min(self.polls, len(self.track) - 1)]
            self.polls += 1
            return 200, [{"bikeId": "BIKE1",
                          "location": {"coordinate": {"latitude": lat, "longitude": lon,
                                                      "accuracyRadius": 10}},
                          "iotTelemetry": {"moduleCharge": 90}}]
        if "/TELEMETRY/history" in url:
            self.telemetry_calls += 1
            return 403, None
        raise AssertionError(f"unexpected {method} {url}")


async def _run_polls(r, monkeypatch, fake: FakePon, polls: int) -> None:
    async def ha_get(path):
        assert path == "/states/zone.home"
        return {"attributes": {"latitude": HOME[0], "longitude": HOME[1], "radius": 100}}

    monkeypatch.setattr(r, "PON_CLIENT_ID", "client")
    monkeypatch.setattr(r, "PON_BIKE_ID", "")
    monkeypatch.setattr(r, "_pon_refresh", "refresh-1")
    monkeypatch.setenv("PON_REFRESH", "refresh-1")
    monkeypatch.setattr(r, "PON_POLL", 0.01)
    monkeypatch.setattr(r, "PON_POLL_HOME", 0.01)
    monkeypatch.setattr(r, "_http_json", fake.http_json)
    monkeypatch.setattr(r, "_ha_get", ha_get)
    task = asyncio.create_task(r.pon_cloud_loop())
    try:
        deadline = time.monotonic() + 5
        while fake.polls < polls and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.02)          # let the last poll finish processing
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert fake.polls >= polls


async def test_forbidden_telemetry_is_skipped_not_hammered(r, monkeypatch, caplog):
    fake = FakePon([HOME] * 6)
    with caplog.at_level(logging.INFO, logger="bosch-reader"):
        await _run_polls(r, monkeypatch, fake, polls=6)
    # One request + one retry with a fresh token, then backed off for an hour.
    assert fake.telemetry_calls == 2
    assert fake.token_calls == 2
    warnings = [m for m in caplog.messages if "TELEMETRY" in m]
    assert len(warnings) == 1
    assert "BIKE1" not in warnings[0]            # no ids / queries in the log


async def test_ride_detected_from_gps_without_telemetry(r, monkeypatch, fake_mqtt):
    track = [HOME, HOME, north(600), north(1500), north(1500), north(2300),
             north(2300), north(2300), north(2300)]
    fake = FakePon(track)
    await _run_polls(r, monkeypatch, fake, polls=len(track))
    assert _types(r) == ["ride_start", "left_home", "ride_stop"]
    states = fake_mqtt.topic(r.CLOUD_STATE_TOPIC)
    assert "moving" in states and states[-1] == "parked"
    assert r._last["cloud"]["motion_source"] == "gps"


async def test_arrival_heard_over_ble_stops_the_ride_at_once(r, monkeypatch):
    track = [north(3000), north(2000), north(1000), HOME, HOME]
    fake = FakePon(track)

    real_moving = r._gps_moving

    def moving(lat, lon, acc=0, *, near_home=False):
        if (lat, lon) == HOME:                   # the tracker is heard at home
            r._tracker_seen_ts = time.time()
            near_home = r._tracker_near()
        return real_moving(lat, lon, acc, near_home=near_home)

    monkeypatch.setattr(r, "_gps_moving", moving)
    await _run_polls(r, monkeypatch, fake, polls=4)
    assert _types(r) == ["ride_start", "ride_stop", "arrived_home"]
    assert "moved" not in _types(r)


@pytest.mark.parametrize("near", [True, False])
def test_tracker_near(r, near):
    r._tracker_seen_ts = time.time() - (10 if near else r.TRACKER_NEAR_S + 5)
    assert r._tracker_near() is near
