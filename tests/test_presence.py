"""Passive presence guard: the tracker is only listened for, never connected."""

from __future__ import annotations

import json

import pytest

T0 = 1_000_000.0


@pytest.fixture
def p(r, fake_mqtt, monkeypatch):
    """Reader with fresh presence state and a presence sensor that may alarm."""
    monkeypatch.setattr(r, "_pres", {"present": None, "had": False, "alarm_edge": False,
                                     "prev_seen": 0.0, "gaps": [], "gap_pub": None})
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
    for at in (T0, T0 + 20, T0 + 140, T0 + 160):
        hear(p, at)
        p._presence_eval(at)
    assert fake_mqtt.topic(p.PRESENCE_GAP_TOPIC)[-1] == "120"
    hear(p, T0 + 90_000)                            # next day; old gaps expire
    p._presence_eval(T0 + 90_000)
    assert fake_mqtt.topic(p.PRESENCE_GAP_TOPIC)[-1] == "0"


async def test_status_reports_passive_guard(p, monkeypatch):
    monkeypatch.setattr(p, "_tracker_always", False)
    monkeypatch.setattr(p, "_probe_frames", False)
    resp = await p._ui_status(None)
    body = json.loads(resp.body)
    assert body["passive_guard"] is True
    assert body["alarm_grace_min"] == 5
