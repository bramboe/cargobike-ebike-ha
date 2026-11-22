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



async def test_interactive_insights_planning_filters_export_and_mobile(r, monkeypatch, tmp_path):
    """Interactions stay read-only and survive automatic status refresh."""
    import csv
    import time
    from aiohttp import web
    from playwright.async_api import async_playwright

    now = time.time()
    r._last.update(last_updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), battery=80,
                   insights={
                       'local_battery_soh': 94, 'local_battery_voltage': None,
                       'service_remaining_km': 200, 'km_per_ride': 10, 'rides_per_week': 5,
                       'connection': {'state': 'reading_ok', 'age_seconds': 20},
                       'receiver_health': 'ok',
                       'readings': {'battery_soh': {'at': now, 'status': 'available'},
                                    'battery_voltage': {'at': now, 'status': 'denied'}},
                       'capabilities': {'00d8': 'available', '008c': 'denied'},
                       'components': {'drive': {'model': XSS_CLOUD}},
                       'forecast': {'forecast_status': 'estimated', 'service_days': 28,
                                    'service_weeks': 4, 'history_days': 14,
                                    'rides': [
                                        {'end': now - 2 * 86400, 'km': 10, 'quality': 'inferred', 'battery_drop': 3},
                                        {'end': now - 10 * 86400, 'km': 18, 'quality': 'interval', 'battery_drop': None},
                                        {'end': now - 40 * 86400, 'km': 20, 'quality': 'inferred', 'battery_drop': 5},
                                    ]},
                   })
    runner = web.AppRunner(r.make_app())
    await runner.setup()
    port = _free_port()
    await web.TCPSite(runner, '127.0.0.1', port).start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(locale='en-GB', accept_downloads=True)
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            await page.goto(f'http://127.0.0.1:{port}/')
            await page.wait_for_function("document.querySelector('.metric').textContent.includes('94')")
            await page.locator('.metric').first.click()
            assert 'not a capacity test' in await page.locator('#metricDetail').inner_text()
            await page.get_by_role('tab', name='Maintenance', exact=True).click()
            await page.locator('#scenarioHeading').click()
            assert '28 days / 4 weeks' in await page.locator('#scenarioResult').inner_text()
            await page.locator('#scenarioKm').fill('20')
            assert '14 days / 2 weeks' in await page.locator('#scenarioResult').inner_text()
            await page.evaluate('refresh()')
            assert await page.locator('#scenarioKm').input_value() == '20'
            assert await page.locator('#insight-tab-maintenance').get_attribute('aria-selected') == 'true'
            assert r._last['insights']['forecast']['service_days'] == 28
            await page.locator('#scenarioReset').click()
            assert await page.locator('#scenarioKm').input_value() == '10'
            await page.get_by_role('tab', name='Rides', exact=True).click()
            assert await page.locator('#rideList tbody tr').count() == 2
            await page.locator('#ridePeriod').select_option('7')
            assert await page.locator('#rideList tbody tr').count() == 1
            await page.locator('#rideKind').select_option('interval')
            assert await page.locator('#rideExport').is_disabled()
            await page.locator('#rideKind').select_option('all')
            await page.locator('#ridePeriod').select_option('90')
            assert await page.locator('#rideList tbody tr').count() == 3
            assert await page.locator('#rideChart svg rect').count() == 3
            async with page.expect_download() as download_info:
                await page.locator('#rideExport').click()
            download = await download_info.value
            path = tmp_path / 'rides.csv'
            await download.save_as(path)
            with path.open(encoding='utf-8-sig', newline='') as f:
                exported = list(csv.reader(f))
            assert len(exported) == 4
            assert exported[0][0] == 'observed_at'
            await page.get_by_role('tab', name='Connection', exact=True).click()
            await page.locator('#capabilityHeading').click()
            await page.locator('#capabilitySearch').fill('denied')
            assert await page.locator('#capabilityList dt').count() == 1
            assert 'Pack voltage' in await page.locator('#capabilityList').inner_text()
            await page.evaluate('refresh()')
            assert await page.locator('#capabilitySearch').input_value() == 'denied'
            assert await page.evaluate('window.__xss') is None
            assert await page.locator('img[src=x]').count() == 0
            assert 'Service approaching' in await page.locator('#serviceNotice').inner_text()
            r._last['insights']['service_remaining_km'] = -25
            await page.evaluate('refresh()')
            assert '25 km beyond' in await page.locator('#maintenanceCallout').inner_text()
            assert await page.locator('#planningKm').inner_text() == '0 km'
            await page.get_by_role('button', name='Settings', exact=True).click()
            await page.locator('#showMaintenance').uncheck()
            await page.wait_for_function("document.querySelector('#maintenanceSaveStatus').textContent === 'Saved'")
            assert r._show_maintenance is False
            await page.reload()
            await page.wait_for_function("document.querySelector('#insight-tab-battery').textContent === 'Battery'")
            assert await page.locator('#maintenanceCard').is_hidden()
            assert await page.locator('#insight-tab-maintenance').is_hidden()
            await page.get_by_role('button', name='Settings', exact=True).click()
            await page.locator('#showMaintenance').check()
            await page.wait_for_function("document.querySelector('#maintenanceSaveStatus').textContent === 'Saved'")
            assert r._load_cfg()['show_maintenance'] is True
            await page.get_by_role('button', name='Dashboard', exact=True).click()
            # Restored BLE mileage can be available before the insights history.
            r._last['next_service'] = 177
            r._last['insights'].pop('service_remaining_km')
            r._last['insights']['forecast'] = {'forecast_status': 'insufficient_history'}
            await page.evaluate('refresh()')
            assert 'Service approaching' in await page.locator('#serviceNotice').inner_text()
            assert await page.locator('#planningKm').inner_text() == '177 km'
            assert 'Days/weeks not yet known' in await page.locator('#serviceForecast').inner_text()
            assert 'Service timing not yet known' not in await page.locator('#maintenanceCard').inner_text()
            assert 'Service approaching' in await page.locator('#maintenanceCallout').inner_text()
            # Keyboard navigation and a narrow screen retain usable panels.
            await page.locator('#insight-tab-connection').focus()
            await page.keyboard.press('Home')
            assert await page.locator('#insight-tab-battery').get_attribute('aria-selected') == 'true'
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.get_by_role('tab', name='Rides', exact=True).click()
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert errors == []
            await browser.close()
    finally:
        await runner.cleanup()
