"""Small, explicit read-only BES3 data model for BLE.

Addresses/scaling: rweijnen/bosch-bes3-reader, cd9a551, CC BY 4.0.
Only a small allowlist is requested; no arbitrary addresses, writes or RPCs.
"""
from __future__ import annotations

import math


def protobuf(raw):
    fields, pos = {}, 0

    def varint():
        nonlocal pos
        value = 0
        for shift in range(0, 70, 7):
            if pos >= len(raw):
                raise ValueError("truncated varint")
            b = raw[pos]
            pos += 1
            value |= (b & 127) << shift
            if not b & 128:
                return value
        raise ValueError("oversized varint")

    while pos < len(raw):
        tag = varint()
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("invalid field")
        if wire == 0:
            value = varint()
        elif wire == 2:
            size = varint()
            if pos + size > len(raw):
                raise ValueError("truncated bytes")
            value, pos = raw[pos:pos + size], pos + size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if pos + size > len(raw):
                raise ValueError("truncated fixed field")
            value, pos = raw[pos:pos + size], pos + size
        else:
            raise ValueError("unsupported wire type")
        fields[field] = value
    return fields


# address: (component, output key, decoding, factor, plausible min, max)
FIELDS = {
    0x0096: ("battery", "battery_cycles", "uint", 10, 0, 100000),
    0x00D8: ("battery", "battery_soh", "uint", 1, 0, 100),
    0x008C: ("battery", "battery_voltage", "uint", 1000, 10, 70),
    0x008B: ("battery", "battery_temperature", "sint", 10, -50, 100),
    0x0092: ("battery", "battery_remaining_wh", "uint", 10, 0, 2000),
    0x0091: ("battery", "battery_usable_wh", "uint", 10, 0, 2000),
    0x0088: ("battery", "battery", "uint", 1, 0, 100),
    0x1818: ("drive", "odometer", "uint", 1000, 0, 1000000),
    0x1884: ("drive", "motor_temperature", "sint", 10, -50, 150),
    0x2185: ("controller", "service_at_km", "service", 1000, 0, 1000000),
}


def decode(address, payload):
    if address not in FIELDS:
        return None
    comp, key, kind, factor, lo, hi = FIELDS[address]
    f = protobuf(payload)
    value = f.get(2) if kind == "service" else f.get(1, 0)
    if not isinstance(value, int):
        return None
    if kind == "sint":
        value = (value >> 1) ^ -(value & 1)
    value /= factor
    if not math.isfinite(value) or not lo <= value <= hi:
        return None
    return {"component": comp, "key": key, "value": round(value, 3)}


def read_frame(address, sequence):
    if address not in ALLOWED_ADDRESSES:
        raise ValueError("address is not in the read allowlist")
    return bytes((0x30, 5, 0x41, 0x80, 0x80 | (address >> 8), address & 255, sequence & 15))


def response(raw, address, sequence):
    pos = 0
    while pos + 2 <= len(raw):
        kind, size = raw[pos:pos + 2]
        pos += 2
        body = raw[pos:pos + size]
        pos += size
        if kind != 0x30 or len(body) != size or size < 5 or body[0] & 128:
            continue
        if (((body[0] & 127) << 8) | body[1]) != address or body[4] != 0x10 | (sequence & 15):
            continue
        if (((body[2] & 127) << 8) | body[3]) != 0x4180:
            continue
        implicit = body[2] & 128
        if not implicit and size < 6:
            continue
        status = 0 if implicit else body[5]
        return status, body[5 if implicit else 6:]
    return None


IDENTITY_FIELDS = {
    0x0081: ("battery", "serial"), 0x0082: ("battery", "part"),
    0x0083: ("battery", "product_code"), 0x009B: ("battery", "model"),
    0x0084: ("battery", "hardware"), 0x0086: ("battery", "firmware"),
    0x1801: ("drive", "serial"), 0x1802: ("drive", "part"),
    0x1803: ("drive", "product_code"), 0x182E: ("drive", "model"),
    0x1804: ("drive", "hardware"), 0x1806: ("drive", "firmware"),
    0x2061: ("controller", "serial"), 0x2062: ("controller", "part"),
    0x2065: ("controller", "product_code"), 0x206F: ("controller", "model"),
    0x2063: ("controller", "hardware"), 0x206B: ("controller", "firmware"),
    0x0D01: ("display", "serial"), 0x0D03: ("display", "product_code"),
    0x0D09: ("display", "model"), 0x0D06: ("display", "firmware"),
}
ALLOWED_ADDRESSES = frozenset(FIELDS) | frozenset(IDENTITY_FIELDS)
