"""The research probe must never take the proxy's BLE subscriber slot."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    'proxy_check', Path(__file__).parents[1] / 'tools' / 'esphome_proxy_check.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_capabilities_are_prerequisites_not_bosch_validation():
    assert probe.capabilities(1)['missing_for_bosch_trial'] == [
        'active_connections', 'remote_caching', 'pairing']
    ready = probe.capabilities(2 | 4 | 8)
    assert ready['protocol_prerequisites_present'] is True
    assert ready['bosch_hardware_validated'] is False


class FakeAPI:
    api_version = object()

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def connect(self, *, login):
        self.calls.append(('connect', login))

    async def device_info(self):
        self.calls.append(('device_info',))
        if self.fail:
            raise ValueError('test failure')
        return SimpleNamespace(esphome_version='test', model='ESP32',
                               bluetooth_proxy_feature_flags_compat=lambda version: 15)

    def subscribe_bluetooth_connections_free(self, callback):
        self.calls.append(('slots',))
        callback(1, 3, [0xAABBCCDDEEFF])
        return lambda: self.calls.append(('unsubscribe_slots',))

    async def disconnect(self, force=False):
        self.calls.append(('disconnect', force))


async def test_probe_uses_only_non_owning_api_calls():
    api = FakeAPI()
    result = await probe.inspect_proxy(api)
    assert result['slots'] == {'free': 1, 'limit': 3}
    assert 'allocated' not in result['slots']
    assert api.calls == [('connect', True), ('device_info',), ('slots',),
                         ('unsubscribe_slots',), ('disconnect', False)]


async def test_probe_disconnects_after_failure():
    api = FakeAPI(fail=True)
    with pytest.raises(ValueError):
        await probe.inspect_proxy(api)
    assert api.calls[-1] == ('disconnect', False)
