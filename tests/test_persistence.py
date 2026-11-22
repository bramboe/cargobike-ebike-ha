"""On-disk state must never end up half-written."""

from __future__ import annotations

import json
import os

import pytest


def test_atomic_write_replaces_file(r, tmp_path):
    path = str(tmp_path / "x.json")
    r._write_json_atomic(path, {"a": 1})
    r._write_json_atomic(path, {"a": 2})
    with open(path) as fh:
        assert json.load(fh) == {"a": 2}
    assert not os.path.exists(path + ".tmp")


def test_failed_write_keeps_previous_content(r, tmp_path):
    """A write that dies halfway (here: an unserialisable value) leaves the old
    file intact — a rotated refresh token must never be lost to a torn write."""
    path = str(tmp_path / "token.json")
    r._write_json_atomic(path, {"refresh_token": "old"})
    with pytest.raises(TypeError):
        r._write_json_atomic(path, {"refresh_token": object()})
    with open(path) as fh:
        assert json.load(fh) == {"refresh_token": "old"}


def test_token_savers_round_trip(r, monkeypatch):
    r._pon_save_refresh("pon-rt")
    r._bosch_save_refresh("bosch-rt")
    monkeypatch.delenv("PON_REFRESH", raising=False)
    monkeypatch.delenv("BOSCH_REFRESH", raising=False)
    assert r._pon_load_refresh() == "pon-rt"
    assert r._bosch_load_refresh() == "bosch-rt"


def test_config_and_snapshot_saves(r):
    r._last.update({"battery": 55, "motion": True})
    r._save_last()
    r._save_cfg()
    with open(r.LAST_FILE) as fh:
        assert json.load(fh) == {"battery": 55}      # live flags are not persisted
    with open(r.DATA_FILE) as fh:
        assert "sensors" in json.load(fh)


async def test_maintenance_preference_persists_and_rejects_invalid_values(r):
    class Request:
        def __init__(self, data):
            self.data = data

        async def json(self):
            return self.data

    assert r._show_maintenance is True
    response = await r._ui_preferences(Request({'show_maintenance': False}))
    assert response.status == 200
    assert r._load_cfg()['show_maintenance'] is False
    assert (await r._ui_preferences(Request({'show_maintenance': 'false'}))).status == 400
    assert r._show_maintenance is False
