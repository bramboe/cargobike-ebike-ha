"""BLE-only derived sensors and persistent history, independent of MQTT/UI."""
from __future__ import annotations

import json
import os
import time

from diagnostics import FIELDS
from history import RideHistory, number


class Insights:
    def __init__(self, path, *, temperature_low=0, temperature_high=50,
                 voltage_low=30, voltage_high=43.5):
        self.path = path
        try:
            with open(path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        self.history = RideHistory(saved.get("history"))
        self.local = saved.get("local", {})
        self.components = saved.get("components", {})
        self.changes = saved.get("changes", [])[-50:]
        self.connection = {"state": "starting", "last_success": None, "error": None}
        self.remaining = number(saved.get("remaining"))
        self.service_target = number(saved.get("service_target"))
        self.thresholds = {"temperature_low": temperature_low, "temperature_high": temperature_high,
                           "voltage_low": voltage_low, "voltage_high": voltage_high}
        self._saved_at = 0.0

    def save(self, *, force=False):
        self.persist(force=force)

    def reset(self, identity=None):
        self.history.reset(identity)
        self.local, self.components, self.changes, self.remaining = {}, {}, [], None
        self.service_target = None
        self.connection = {"state": "starting", "last_success": None, "error": None}
        self.save(force=True)

    def observe(self, state, *, identity=None, now=None):
        now = time.time() if now is None else now
        if identity and self.history.identity and identity != self.history.identity:
            self.reset(identity)
        km = number(state.get("odometer"))
        remaining = number(state.get("next_service"))
        if remaining is not None:
            self.remaining = remaining
            if km is not None:
                self.service_target = km + remaining
        elif km is not None and self.service_target is not None:
            self.remaining = round(self.service_target - km, 3)
        if "odometer" in state:
            self.history.observe(state["odometer"], state.get("battery"), at=now,
                                 identity=identity, source="ble")
        self.connection.update(state="reading_ok", last_success=now, error=None)

    def enrich(self, result):
        if result.get("source") != "ble":
            raise ValueError("Runtime insights only accept fresh BLE data")
        now = result["measured_at"]
        for name, new in result.get("components", {}).items():
            previous = self.components.get(name, {})
            if previous.get("serial") and new.get("serial") and previous["serial"] != new["serial"]:
                self.changes.append({"at": now, "component": name, "change": "replaced"})
                self.components[name] = {}
                if name == "battery":
                    # A replacement pack must not inherit the old pack's health.
                    self.local = {k: v for k, v in self.local.items()
                                  if not k.startswith("battery_")}
            elif previous.get("firmware") and new.get("firmware") and previous["firmware"] != new["firmware"]:
                self.changes.append({"at": now, "component": name, "change": "firmware"})
            self.components[name] = {**self.components.get(name, {}), **new, "at": now, "source": "ble"}
        for address, status in result.get("capabilities", {}).items():
            spec = FIELDS.get(int(address, 16))
            if not spec:
                continue
            key = spec[1]
            if key in ("battery", "odometer", "service_at_km"):
                continue
            if status == "available" and key in result["values"]:
                self.local[key] = {"value": result["values"][key], "at": now, "source": "ble", "status": status}
            elif status in ("denied", "unsupported", "no_route", "invalid_payload"):
                self.local[key] = {"value": None, "at": now, "source": "ble", "status": status}
        self.local["capabilities"] = result.get("capabilities", {})
        self.changes = self.changes[-50:]

    def snapshot(self, *, now=None):
        now = time.time() if now is None else now
        if self.history.active and now - self.history.active["last_move"] >= 900:
            self.history.finish()
        stats = self.history.summary(self.remaining, now=now)
        # Each field carries its own age: an unrelated successful read cannot
        # make an old SoH or voltage look freshly measured.
        values, details = {}, {}
        for key, reading in self.local.items():
            if key == "capabilities":
                continue
            age = max(0, now - reading.get("at", 0))
            details[key] = {**reading, "age_seconds": round(age), "stale": age > 86400}
            values["local_" + key] = reading.get("value") if age <= 86400 else None
        for field, option in (("battery_temperature", "temperature"), ("battery_voltage", "voltage")):
            v = values.get("local_" + field)
            values[field + "_warning"] = (v < self.thresholds[option + "_low"] or v > self.thresholds[option + "_high"]) if v is not None else None
        last = self.connection.get("last_success")
        state = self.connection["state"]
        if state == "reading_ok" and last is not None and now - last > 600:
            state = "stale"
        return {**values, **{k: stats[k] for k in ("service_days", "service_weeks", "service_rides", "km_per_ride", "rides_per_week", "km_per_day")},
                "service_remaining_km": self.remaining, "service_soon": self.remaining is not None and self.remaining <= 200,
                "forecast": stats, "readings": details, "components": self.components,
                "component_changes": self.changes, "capabilities": self.local.get("capabilities", {}),
                "connection": {**self.connection, "state": state,
                               "age_seconds": round(max(0, now - last)) if last is not None else None},
                "thresholds": self.thresholds, "source": "ble"}

    def persist(self, *, force=False):
        if not force and time.monotonic() - self._saved_at < 30:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"history": self.history.export(), "local": self.local,
                       "components": self.components, "changes": self.changes,
                       "remaining": self.remaining, "service_target": self.service_target}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self._saved_at = time.monotonic()
