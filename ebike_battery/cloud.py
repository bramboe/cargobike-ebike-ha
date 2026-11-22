"""HTTP and typed cloud response parsing, separate from orchestration."""
import json
import logging
try:
    import aiohttp
except ImportError:
    aiohttp = None
log = logging.getLogger("bosch-reader")

async def _http_json(method: str, url: str, *, headers=None, data=None):
    """Tiny aiohttp JSON helper. Returns (status, parsed_json|None)."""
    if aiohttp is None:
        return None, None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.request(method, url, headers=headers, data=data,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                txt = await r.text()
                try:
                    return r.status, json.loads(txt)
                except Exception:  # noqa: BLE001
                    return r.status, None
    except Exception as err:  # noqa: BLE001
        log.debug("http %s %s: %s", method, url, err)
        return None, None


def _bnum(v):
    """Best-effort float — Bosch ships most numeric fields as JSON strings."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _nested_num(v, key):
    """A numeric field Bosch ships either as a scalar or nested under `key`
    (the smart-system profile uses e.g. powerOnTime={'total':..,'withMotorSupport':..}
    and chargeCycles={'total':..,'onBike':..,'offBike':..})."""
    if isinstance(v, dict):
        return _bnum(v.get(key))
    return _bnum(v)


def _parse_service_records(js: dict, battery_serial: "str | None") -> dict:
    """Battery State-of-Health (only if a dealer ran a capacity test → a
    BATTERY_MEASUREMENT record) plus the newest applied software update. The
    smart-system service book otherwise holds only SOFTWARE_UPDATE records; the
    'next service' target lives on the bike's serviceDue, parsed in the loop."""
    out: dict = {}
    records = js.get("serviceRecords") if isinstance(js, dict) else js
    if isinstance(records, dict):
        records = records.get("items") or records.get("records") or []
    records = records or []

    def _created(r):
        return str((r.get("attributes") or {}).get("createdAt")
                   or r.get("createdAt") or "")

    # Battery State-of-Health — newest BATTERY_MEASUREMENT for our pack serial.
    cand = [r for r in records if isinstance(r, dict)
            and r.get("type") == "BATTERY_MEASUREMENT"]
    meas = None
    if battery_serial:
        serial_hits = [r for r in cand
                       if ((r.get("attributes") or {}).get("battery")
                           or {}).get("serialNumber") == battery_serial]
        if serial_hits:
            meas = max(serial_hits, key=_created)
    if meas is None and cand and not battery_serial:
        meas = max(cand, key=_created)
    if meas:
        a = meas.get("attributes") or {}
        m = a.get("measurement") or a
        soh = _bnum(m.get("measuredCapacityPercentage"))
        if soh is not None:
            out["battery_soh"] = round(soh, 1)
        for k, dst in (("measuredEnergyCapacity", "battery_measured_wh"),
                       ("nominalEnergyCapacity", "battery_nominal_wh")):
            v = _bnum(m.get(k))
            if v is not None:
                out[dst] = round(v)

    # Newest applied software update — date + tool version.
    sw = [r for r in records if isinstance(r, dict)
          and r.get("type") == "SOFTWARE_UPDATE"]
    if sw:
        newest = max(sw, key=_created)
        a = newest.get("attributes") or {}
        if a.get("createdAt"):
            out["last_software_update"] = a["createdAt"]
        det = a.get("details") or {}
        ver = det.get("toolVersion")
        if ver:
            out["software_version"] = ver
        brand = (det.get("bike") or {}).get("brandId")
        if brand:
            out["brand"] = brand
    return out


def _parse_capacity_tester(js: dict, battery_serial: "str | None") -> dict:
    """Newest Bosch Capacity Tester measurement (dealer-gated) for our battery."""
    out: dict = {}
    testers = (js.get("capacityTesters") if isinstance(js, dict) else None) or []
    matching = [t for t in testers if isinstance(t, dict) and (
        not battery_serial
        or (t.get("batteryData") or {}).get("serialNumber") == battery_serial
        or t.get("serialNumber") == battery_serial)]
    if not matching:
        return out
    newest = max(matching, key=lambda t: str(t.get("createdAt") or ""))
    bd = newest.get("batteryData") or {}
    for k, dst in (("measuredCapacity", "capacity_tested_wh"),
                   ("nominalCapacity", "capacity_nominal_wh"),
                   ("fullChargeCycles", "capacity_cycles")):
        v = _bnum(bd.get(k))
        if v is not None:
            out[dst] = round(v)
    if newest.get("createdAt"):
        out["capacity_tested_at"] = newest["createdAt"]
    return out


