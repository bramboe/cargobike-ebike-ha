"""Bosch telemetry decoders; no Bluetooth, MQTT or global runtime state."""
import re
FIELD_BATTERY = 10
MODE_NAMES = {1: "Eco", 2: "Tour", 3: "Auto", 4: "Turbo"}

def _pb_fields(raw: bytes) -> dict[int, object]:
    """Decode a flat protobuf into {field_number: int | bytes}."""
    fields: dict[int, object] = {}
    pos = 0

    def rv(d: bytes, p: int) -> tuple[int, int]:
        result = shift = 0
        while p < len(d):
            b = d[p]
            p += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result, p

    while pos < len(raw):
        try:
            tag, pos = rv(raw, pos)
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                fields[fn], pos = rv(raw, pos)
            elif wt == 2:
                ln, pos = rv(raw, pos)
                fields[fn] = raw[pos:pos + ln]
                pos += ln
            elif wt == 5:
                fields[fn] = int.from_bytes(raw[pos:pos + 4], "little")
                pos += 4
            elif wt == 1:
                fields[fn] = int.from_bytes(raw[pos:pos + 8], "little")
                pos += 8
            else:
                break
        except Exception:  # noqa: BLE001
            break
    return fields


def parse_eb21(raw: bytes) -> dict[str, int | float]:
    """Decode the eb21 snapshot. Known fields:
      f10 = battery %, f12 = odometer (metres),
      f20.f2 = odometer at which the next service is due (metres).
    Returns battery, odometer (km) and next_service (km remaining) when present.
    """
    f = _pb_fields(raw)
    out: dict[str, int | float] = {}
    if isinstance(f.get(FIELD_BATTERY), int):
        out["battery"] = f[FIELD_BATTERY]  # type: ignore[index]
    odo = f.get(12)
    if isinstance(odo, int):
        out["odometer"] = round(odo / 1000, 3)
        target = _pb_fields(f[20]).get(2) if isinstance(f.get(20), bytes) else None
        if isinstance(target, int):
            out["next_service"] = round((target - odo) / 1000, 3)
    return out


def parse_eb41_frame(raw: bytes) -> str | None:
    """eb41 field 9 carries the frame number string, e.g. '0000000EXMP'."""
    v = _pb_fields(raw).get(9)
    if isinstance(v, (bytes, bytearray)) and len(v) >= 6 and all(32 <= c < 127 for c in v):
        return bytes(v).decode()
    return None


# Component subsystem per record attribute high byte (push 0x001e records:
# 30 LL <attr:2> c0 80 10 0a <slen> <ascii>). Each subsystem reports its own
# firmware (a 19.x.x string) and production date (dd.mm.yyyy).
_COMP_GROUP = {0x20: "controller", 0x18: "drive", 0x00: "battery", 0x0d: "display"}
_DATE_RE = re.compile(r"^\d\d\.\d\d\.\d{4}$")
_FW_RE = re.compile(r"^\d{1,3}\.\d+\.\d+$")


def _comp_string(buf: bytes, attr2: int) -> "str | None":
    """Return the ASCII string of the component record with the given 2-byte
    attribute (record: 30 LL <attr2> c0 80 <Y> 0a <len> <ascii>)."""
    hi, lo = attr2 >> 8, attr2 & 0xFF
    i = 0
    while i < len(buf) - 1:
        if buf[i] != 0x30:
            i += 1
            continue
        ln = buf[i + 1]
        rec = buf[i + 2:i + 2 + ln]
        i += 2 + ln
        if len(rec) < 5 or rec[0] != hi or rec[1] != lo:
            continue
        m = rec.find(0x0A, 2)
        if m < 0 or m + 1 >= len(rec):
            continue
        s = rec[m + 2:m + 2 + rec[m + 1]]
        if s and all(32 <= c < 127 for c in s):
            return s.decode()
    return None


def _lock_state(buf: bytes) -> "int | None":
    """eBike Lock state readback: record 30 LL 0d1c c0 80 <M> 08 02. Returns the
    method byte M (0x50 = phone, 0x51 = phone+Kiox) when locked, or None when the
    record is absent (= unlocked)."""
    i = 0
    while i < len(buf) - 1:
        if buf[i] != 0x30:
            i += 1
            continue
        ln = buf[i + 1]
        rec = buf[i + 2:i + 2 + ln]
        i += 2 + ln
        if (len(rec) >= 5 and rec[0] == 0x0D and rec[1] == 0x1C
                and rec[2] == 0xC0 and rec[3] == 0x80):
            return rec[4]
    return None


def parse_components(buf: bytes) -> dict:
    """Group the Bosch component-info strings by subsystem and pull each one's
    headline firmware and production date. Returns
    {subsystem: {firmware, date}} — names come from content matches elsewhere."""
    by: dict[str, list[str]] = {}
    i = 0
    while i < len(buf) - 1:
        if buf[i] != 0x30:
            i += 1
            continue
        ln = buf[i + 1]
        rec = buf[i + 2:i + 2 + ln]
        i += 2 + ln
        if len(rec) < 3:
            continue
        m = rec.find(b"\xc0\x80\x10\x0a")  # string marker
        if m < 1:
            continue
        slen = rec[m + 4] if m + 4 < len(rec) else 0
        s = rec[m + 5:m + 5 + slen]
        if not s or not all(32 <= c < 127 for c in s):
            continue
        grp = _COMP_GROUP.get(rec[0])
        if grp:
            by.setdefault(grp, []).append(s.decode())
    out: dict[str, dict] = {}
    for grp, strs in by.items():
        fw = next((x for x in strs if _FW_RE.match(x)), None)
        date = next((x for x in strs if _DATE_RE.match(x)), None)
        if fw or date:
            out[grp] = {"firmware": fw, "date": date}
    return out


def parse_mode(raw: bytes) -> str | None:
    """Return the ride mode from a Bosch push-channel notification, or None.

    On record:  ... 98 09 08 <level> ...  (level 1=Eco 2=Tour 3=Auto 4=Turbo)
    Off record: ... 30 02 98 09 ...        (a length-2 record, no level byte)
    """
    i = raw.find(b"\x98\x09")
    while i != -1:
        if i + 3 < len(raw) and raw[i + 2] == 0x08 and raw[i + 3] in MODE_NAMES:
            return MODE_NAMES[raw[i + 3]]
        if i >= 2 and raw[i - 2] == 0x30 and raw[i - 1] == 0x02:
            return "Off"
        i = raw.find(b"\x98\x09", i + 2)
    return None


def parse_range(raw: bytes) -> dict[str, int] | None:
    """Return the estimated range (km) per mode from a push notification.

    Attribute 9857 carries a 4-byte array `98 57 0a 04 <eco><tour><auto><turbo>`
    (ascending assist order, each a km value).
    """
    i = raw.find(b"\x98\x57\x0a\x04")
    if i != -1 and i + 8 <= len(raw):
        a = raw[i + 4:i + 8]
        return {"eco": a[0], "tour": a[1], "auto": a[2], "turbo": a[3]}
    return None


def parse_power_profile(raw: bytes) -> dict[str, float] | None:
    """Return the drive-unit assist map from push attr 1090/1091, or None.

    Record: `10 90 c0 80 <seq> 08 <f1> 10 <torque> 18 <f3> 20 <speed×100> 28 <power>`
    f2 = max torque (Nm), f4 = assist speed cutoff (km/h ×100), f5 = max power (W).
    Static config (same every read); sanity-bounded so a stray match is ignored.
    """
    for attr in (b"\x10\x90", b"\x10\x91"):
        i = raw.find(attr + b"\xc0\x80")
        if i == -1:
            continue
        f = _pb_fields(raw[i + 5:i + 19])  # skip attr(2) + c0 80 + seq(1)
        torque, speed, power = f.get(2), f.get(4), f.get(5)
        if (isinstance(torque, int) and isinstance(speed, int)
                and isinstance(power, int) and 0 < torque < 200
                and 1000 < speed < 6000 and 100 < power < 2000):
            return {"max_torque": torque, "speed_limit": round(speed / 100, 1),
                    "max_power": power}
    return None


