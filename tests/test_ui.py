"""The ingress panel: only reachable via HA's ingress, and never runs injected HTML."""

from __future__ import annotations

import socket

import pytest

XSS_BLE = 'URBANARROW<img src=x onerror="window.__xss=\'ble\'">'
XSS_HA = '<img src=x onerror="window.__xss=\'ha\'">'
XSS_CLOUD = '<img src=x onerror="window.__xss=\'cloud\'">'


@pytest.mark.parametrize(("peer", "ok"), [
    ("172.30.32.2", True), ("::ffff:172.30.32.2", True), ("127.0.0.1", True),
    ("172.30.33.5", False), ("192.168.1.20", False), (None, False)])
def test_peer_allowed(r, peer, ok):
    assert r._peer_allowed(peer) is ok


async def test_api_refuses_non_ingress_clients(r, aiohttp_client, monkeypatch):
    client = await aiohttp_client(r.make_app())
    assert (await client.get("/api/status")).status == 200        # 127.0.0.1
    monkeypatch.setattr(r, "INGRESS_PEERS", frozenset({"172.30.32.2"}))
    resp = await client.post("/api/alarm", json={"cmd": "DISARM"})
    assert resp.status == 403
    assert r._alarm["state"] == "disarmed" and not r._alarm["restored"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_panel_escapes_untrusted_names(r, monkeypatch):
    """Names from nearby BLE devices, HA entities and the cloud are shown as text,
    never executed (the panel runs in Home Assistant's origin via ingress)."""
    playwright = pytest.importorskip("playwright.async_api")
    from aiohttp import web

    async def scan(_request):
        return web.json_response([{"address": "AA:BB:CC:DD:EE:FF", "name": XSS_BLE,
                                   "kind": "tracker", "rssi": -50, "module_mac": None,
                                   "ts": 0}])

    async def ha_entities():
        return [{"entity_id": "binary_sensor.bike", "name": XSS_HA,
                 "device_class": "vibration", "state": "off", "match": True}]

    monkeypatch.setattr(r, "_ui_scan", scan)
    monkeypatch.setattr(r, "list_ha_motion_entities", ha_entities)
    monkeypatch.setattr(r, "_bike_addr", XSS_CLOUD)
    monkeypatch.setattr(r, "SUPERVISOR_TOKEN", "token")      # show the sensor card
    ext = r._sensor_row(entity_id="binary_sensor.bike", name=XSS_HA, id="ext1")
    monkeypatch.setitem(r._sensors, "external", [ext])
    r._last.update({
        "last_updated": "2026-09-26T10:00:00+0200", "battery": 80,
        "part_number": XSS_CLOUD, "module_manufacturer": XSS_CLOUD,
        "bosch": {"software_version": XSS_CLOUD, "ts": "2026-09-26T10:00:00+0200"},
        "activity_log": [{"ts": "2026-09-26T10:00:00+0200", "type": XSS_CLOUD,
                          "lat": 52.0, "lon": 5.0}],
    })

    runner = web.AppRunner(r.make_app())
    await runner.setup()
    port = _free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        async with playwright.async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.goto(f"http://127.0.0.1:{port}/")
            await page.wait_for_function(
                "document.querySelector('#techInfo').textContent.includes('onerror')")
            await page.evaluate("scan('tracker','#trackers')")
            await page.wait_for_function(
                "document.querySelector('#trackers').textContent.includes('URBANARROW')")
            await page.evaluate("tab('set')")
            await page.wait_for_function(
                "document.querySelector('#sensList') &&"
                " document.querySelector('#sensList').textContent.includes('onerror')")
            await page.wait_for_timeout(300)
            assert await page.evaluate("window.__xss") is None
            assert await page.evaluate("document.querySelectorAll('img[src=x]').length") == 0
            await browser.close()
    finally:
        await runner.cleanup()
