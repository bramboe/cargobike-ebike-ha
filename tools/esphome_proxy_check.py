#!/usr/bin/env python3
"""Inspect ESPHome API capabilities without taking Bluetooth ownership.

Never subscribes to advertisements, connects to a peripheral, pairs, or writes
GATT. API authentication uses BLE_PROXY_KEY or existing /data/options.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

FEATURES = {
    'passive_scan': 1, 'active_connections': 2, 'remote_caching': 4,
    'pairing': 8, 'cache_clearing': 16, 'raw_advertisements': 32,
    'scanner_state': 64, 'connection_parameters': 128,
}


def capabilities(flags):
    supported = {name: bool(flags & mask) for name, mask in FEATURES.items()}
    missing = [name for name in ('active_connections', 'remote_caching', 'pairing')
               if not supported[name]]
    return {'features': supported, 'missing_for_bosch_trial': missing,
            'protocol_prerequisites_present': not missing,
            'bosch_hardware_validated': False}


async def inspect_proxy(client, *, timeout=10):
    """Device info and a slot-count snapshot only; no Bluetooth subscriber claim."""
    unsubscribe = None
    try:
        await asyncio.wait_for(client.connect(login=True), timeout)
        info = await asyncio.wait_for(client.device_info(), timeout)
        version = client.api_version
        if version is None:
            raise ValueError('No negotiated ESPHome API version')
        flags = info.bluetooth_proxy_feature_flags_compat(version)
        result = {'esphome_version': info.esphome_version, 'model': info.model,
                  **capabilities(flags), 'slots': None}
        if flags & FEATURES['active_connections']:
            future = asyncio.get_running_loop().create_future()

            def on_slots(free, limit, allocated):
                if not future.done():
                    # Never include other peripherals' addresses in output.
                    future.set_result({'free': free, 'limit': limit})

            unsubscribe = client.subscribe_bluetooth_connections_free(on_slots)
            try:
                result['slots'] = await asyncio.wait_for(future, min(timeout, 5))
            except asyncio.TimeoutError:
                result['slot_status'] = 'No slot-count response; no BLE connection attempted'
        return result
    finally:
        try:
            if unsubscribe:
                unsubscribe()
        finally:
            try:
                await asyncio.wait_for(client.disconnect(), min(timeout, 5))
            except Exception:
                # Terminate the API socket even if a graceful close fails.
                await asyncio.wait_for(client.disconnect(force=True), 2)


def config(args):
    options = {}
    if args.options.exists():
        options = json.loads(args.options.read_text())
        if not isinstance(options, dict):
            raise ValueError('Options must be a JSON object')
    host = args.host or os.getenv('BLE_PROXY_HOST') or options.get('ble_proxy_host')
    key = os.getenv('BLE_PROXY_KEY') or options.get('ble_proxy_key')
    port = args.port or int(os.getenv('BLE_PROXY_PORT') or options.get('ble_proxy_port') or 6053)
    if not host or not key:
        raise ValueError('Configure ble_proxy_host/key or BLE_PROXY_HOST/BLE_PROXY_KEY')
    if not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    return host, port, key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', help='Proxy hostname or IP; otherwise existing configuration')
    parser.add_argument('--port', type=int)
    parser.add_argument('--options', type=Path, default=Path('/data/options.json'))
    args = parser.parse_args()
    try:
        host, port, key = config(args)
        from aioesphomeapi import APIClient
        client = APIClient(host, port, None, noise_psk=key)
        result = asyncio.run(inspect_proxy(client))
    except Exception as err:
        # Library exceptions may embed connection parameters: keep them out of output.
        print(json.dumps({'ok': False, 'error_type': type(err).__name__,
                          'hint': 'Check proxy address, API key, firmware and reachability'}))
        return 1
    print(json.dumps({'ok': True, **result}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
