"""Passive presence guard: the tracker is only listened for, never connected."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

T0 = 1_000_000.0


@pytest.fixture
def p(r, fake_mqtt, monkeypatch):
    """Reader with fresh presence state and a presence sensor that may alarm."""
    monkeypatch.setattr(r, "_pres", {"present": None, "had": False, "alarm_edge": False,
                                     "prev_seen": 0.0, "gaps": [], "gap_pub": None,
                                     "mode": None, "guard_since": 0.0})
    monkeypatch.setattr(r, "_cloud_home", {"home": None, "at": 0.0})
    monkeypatch.setattr(r, "_discovered", {})
    monkeypatch.setattr(r, "_tracker_mac", "94:80:58:6E:BE:E9")
    monkeypatch.setattr(r, "_alarm_off", False)
    monkeypatch.setattr(r, "_motion_src", {})
    monkeypatch.setattr(r, "_src_off_since", {})
    monkeypatch.setattr(r, "_group_active", {})
    monkeypatch.setattr(r, "_armed_at", 0.0)
    monkeypatch.setattr(r, "PRESENCE_GRACE", 600.0)
    monkeypatch.setattr(r, "PRESENCE_ALARM_GRACE", 300.0)
    monkeypatch.setattr(r, "_sensors", {
        "entry_delay": 0, "exit_delay": 0, "groups": {},
        "builtin": {
            "tracker_motion": {"enabled": False, "role": "alarm",
                               "modes": ["armed_away"]},
            "presence": {"enabled": True, "role": "alarm",
                         "modes": ["armed_away", "armed_home", "armed_night"]},
        }})
    return r


def hear(r, at: float) -> None:
    r._tracker_seen_ts = at


def test_restart_with_bike_present_does_not_flash_out_of_range(p, fake_mqtt):
    p._last["tracker_present"] = True
    p._presence_seed(T0)
    p._presence_eval(T0 + 30)                       # no scan hit yet
    assert "OFF" not in fake_mqtt.topic(p.PRESENCE_TOPIC)
    assert p._pres["present"] is True


def test_cold_start_without_history_reports_out_of_range(p, fake_mqtt):
    p._presence_seed(T0)
    p._presence_eval(T0)
    assert fake_mqtt.topic(p.PRESENCE_TOPIC) == ["OFF"]


def test_disappearing_tracker_trips_the_armed_alarm_once(p, fake_mqtt):
    p._alarm["state"] = "armed_away"
    hear(p, T0)
    p._presence_eval(T0)
    p._presence_eval(T0 + 299)
    assert p._alarm["state"] == "armed_away"
    p._presence_eval(T0 + 300)
    assert p._alarm["state"] == "triggered"
    attrs = json.loads(fake_mqtt.topic(p.ALARM_ATTR_TOPIC)[-1])
    assert attrs["reason"] == "presence"
    fake_mqtt.published.clear()
    p._presence_eval(T0 + 400)
    assert fake_mqtt.topic(p.ALARM_ATTR_TOPIC) == []


def test_disarmed_absence_only_updates_in_range(p, fake_mqtt):
    hear(p, T0)
    p._presence_eval(T0)
    p._presence_eval(T0 + 700)
    assert p._alarm["state"] == "disarmed"
    assert fake_mqtt.topic(p.PRESENCE_TOPIC) == ["ON", "OFF"]


def test_arming_while_the_bike_is_away_never_trips(p):
    p._alarm["state"] = "armed_away"
    p._presence_eval(T0 + 10_000)                   # never heard since start
    assert p._alarm["state"] == "armed_away"


def test_hearing_it_again_rearms_the_edge(p):
    hear(p, T0)
    p._presence_eval(T0)
    p._presence_eval(T0 + 400)                      # absent while disarmed: edge used
    assert p._pres["alarm_edge"] is True
    hear(p, T0 + 450)
    p._presence_eval(T0 + 450)
    assert p._pres["alarm_edge"] is False
    p._alarm["state"] = "armed_night"
    p._presence_eval(T0 + 450 + 300)
    assert p._alarm["state"] == "triggered"


def test_longest_silence_is_published_and_ages_out(p, fake_mqtt):
    p._pres.update(mode="guard", guard_since=T0 - 1)
    for at in (T0, T0 + 20, T0 + 140, T0 + 160):
        hear(p, at)
        p._presence_eval(at)
    assert fake_mqtt.topic(p.PRESENCE_GAP_TOPIC)[-1] == "120"
    hear(p, T0 + 90_000)                            # next day; old gaps expire
    p._presence_eval(T0 + 90_000)
    assert fake_mqtt.topic(p.PRESENCE_GAP_TOPIC)[-1] == "0"


def test_longest_silence_only_counts_while_guarding(p, fake_mqtt):
    p._pres["mode"] = "normal"                      # disarmed: slow cadence
    for at in (T0, T0 + 28, T0 + 56):
        hear(p, at)
        p._presence_eval(at)
    p._pres.update(mode="guard", guard_since=T0 + 60)
    for at in (T0 + 70, T0 + 82, T0 + 86):          # 56->70 straddles arming
        hear(p, at)
        p._presence_eval(at)
    assert fake_mqtt.topic(p.PRESENCE_GAP_TOPIC)[-1] == "12"   # not 28 or 14


async def test_status_reports_passive_guard(p, monkeypatch):
    monkeypatch.setattr(p, "_tracker_always", False)
    monkeypatch.setattr(p, "_probe_frames", False)
    resp = await p._ui_status(None)
    body = json.loads(resp.body)
    assert body["passive_guard"] is True
    assert body["alarm_grace_s"] == 300


# ------------------------------------------------------------ scan cadence


def test_armed_bike_at_home_is_guarded(p):
    hear(p, T0)
    p._alarm["state"] = "armed_night"
    assert p._presence_mode(T0 + 5) == "guard"
    p._alarm["state"] = "disarmed"
    assert p._presence_mode(T0 + 5) == "normal"


def test_fresh_gps_away_pauses_listening(p):
    hear(p, T0)
    p._cloud_home.update(home=False, at=T0 + 200)
    assert p._presence_mode(T0 + 300) == "paused"
    p._alarm["state"] = "armed_away"                # armed but gone: still paused
    assert p._presence_mode(T0 + 300) == "paused"


def test_listening_resumes_when_gps_says_home_or_goes_stale(p):
    p._cloud_home.update(home=False, at=T0)
    assert p._presence_mode(T0 + 60) == "paused"
    assert p._presence_mode(T0 + p.CLOUD_FRESH_S + 1) == "normal"   # stale fix
    p._cloud_home.update(home=True, at=T0 + 100)
    assert p._presence_mode(T0 + 120) == "normal"


def test_heard_over_ble_never_pauses(p):
    p._cloud_home.update(home=False, at=T0)         # GPS lags behind the arrival
    hear(p, T0 + 10)
    assert p._presence_mode(T0 + 20) == "normal"


def _advert(name: str, module_mac: str):
    mac = bytes(int(x, 16) for x in module_mac.split(":"))
    return (SimpleNamespace(address="DE:34:00:00:00:01", name=name),
            SimpleNamespace(rssi=-70, manufacturer_data={0x020F: mac + b"\x00\x01"}))


def test_any_scan_hearing_our_tracker_counts_for_presence(p, monkeypatch):
    monkeypatch.setattr(p.time, "time", lambda: T0)
    p._record(*_advert("URBANARROW", "94:80:58:6E:BE:E9"))
    assert p._tracker_seen_ts == T0


def test_a_neighbours_tracker_does_not_count(p):
    p._record(*_advert("URBANARROW", "11:22:33:44:55:66"))
    assert p._tracker_seen_ts == 0.0
