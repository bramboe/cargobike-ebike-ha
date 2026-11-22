"""Best-effort READ-only enrichment on the existing bonded BLE connection.

Uses the existing MCSP notification subscription; never creates a second
connection, changes a setting, or falls back to stored USB measurements.
"""
from __future__ import annotations

import asyncio
import time

from diagnostics import ALLOWED_ADDRESSES, FIELDS, IDENTITY_FIELDS, decode, protobuf, read_frame, response

STATUS = {0: "available", 2: "no_route", 3: "not_ready", 4: "unsupported", 6: "denied"}


class DiagnosticReader:
    def __init__(self):
        self.buffer = bytearray()
        self.fragments = bytearray()
        self.pending = None
        self.sequence = 0
        self.capabilities = {}

    def feed(self, data):
        """Reassemble segmentation frames across GATT notifications (bounded)."""
        self.buffer.extend(data)
        if len(self.buffer) > 8192:
            self.buffer.clear()
            self.fragments.clear()
            return
        while len(self.buffer) >= 2:
            header = self.buffer[0]
            size = ((header & 15) << 8) | self.buffer[1]
            if len(self.buffer) < size + 2:
                break
            body = bytes(self.buffer[2:size + 2])
            del self.buffer[:size + 2]
            if (header >> 5) & 7 != 1:
                continue
            self.fragments.extend(body)
            if len(self.fragments) > 4095:
                self.fragments.clear()
                continue
            if header & 16:
                message = bytes(self.fragments)
                self.fragments.clear()
                if self.pending and len(message) < 256:
                    address, seq, future = self.pending
                    parsed = response(bytes((0x30, len(message))) + message, address, seq)
                    if parsed is not None and not future.done():
                        future.set_result(parsed)

    async def collect(self, client, characteristic, *, budget=12.0):
        self.buffer.clear()
        self.fragments.clear()
        values, components, caps = {}, {}, {}
        deadline, consecutive_timeouts = time.monotonic() + budget, 0
        for address in sorted(ALLOWED_ADDRESSES):
            if time.monotonic() >= deadline or consecutive_timeouts >= 3:
                break
            cached = self.capabilities.get(address)
            if cached and cached[0] in ("denied", "unsupported", "no_route") and time.monotonic() - cached[1] < 21600:
                caps[f"{address:04x}"] = cached[0]
                continue
            seq = self.sequence & 15
            self.sequence += 1
            future = asyncio.get_running_loop().create_future()
            self.pending = (address, seq, future)
            try:
                await client.write_gatt_char(characteristic, read_frame(address, seq), response=False)
                status, raw = await asyncio.wait_for(future, timeout=min(0.65, max(0.01, deadline - time.monotonic())))
                consecutive_timeouts = 0
                state = STATUS.get(status, f"status_{status}")
                if status == 0:
                    if address in IDENTITY_FIELDS:
                        comp, key = IDENTITY_FIELDS[address]
                        v = protobuf(raw).get(1)
                        if isinstance(v, bytes):
                            text = v.decode("utf-8", errors="strict").strip()
                            if text and len(text) <= 128 and all(ch.isprintable() for ch in text):
                                components.setdefault(comp, {})[key] = text
                    elif address in FIELDS:
                        parsed = decode(address, raw)
                        if parsed:
                            values[parsed["key"]] = parsed["value"]
                        else:
                            state = "invalid_payload"
            except asyncio.TimeoutError:
                state = "timeout"
                consecutive_timeouts += 1
            except (ValueError, UnicodeError):
                state = "invalid_payload"
            finally:
                self.pending = None
            caps[f"{address:04x}"] = state
            self.capabilities[address] = (state, time.monotonic())
            await asyncio.sleep(0.025)
        return {"values": values, "components": components, "capabilities": caps,
                "source": "ble", "measured_at": time.time()}

    def reset(self):
        self.capabilities.clear()
        self.buffer.clear()
        self.fragments.clear()
