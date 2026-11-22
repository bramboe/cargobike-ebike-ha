"""Persistent, source-independent mileage/ride history and service forecasts.

No GPS is required. Gaps are labelled as intervals: one observation after a
week away must never masquerade as one precisely measured ride.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

DAY = 86400


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class RideHistory:
    def __init__(self, data=None):
        data = data if isinstance(data, dict) else {}
        self.identity = data.get("identity")
        self.samples = [s for s in data.get("samples", []) if isinstance(s, dict)
                        and number(s.get("at")) is not None
                        and number(s.get("km")) is not None][-10000:]
        self.rides = [r for r in data.get("rides", []) if isinstance(r, dict)
                      and number(r.get("km")) is not None][-1000:]
        self.active = data.get("active") if isinstance(data.get("active"), dict) else None

    def export(self):
        return {"version": 1, "identity": self.identity, "samples": self.samples,
                "rides": self.rides, "active": self.active}

    def reset(self, identity=None):
        self.identity, self.samples, self.rides, self.active = identity, [], [], None

    def observe(self, km, battery=None, *, at, identity=None, source="ble"):
        km, battery = number(km), number(battery)
        if km is None or km < 0 or not math.isfinite(at):
            return False
        if identity and self.identity and identity != self.identity:
            self.reset(identity)
        if identity:
            self.identity = identity
        if battery is not None and not 0 <= battery <= 100:
            battery = None
        previous = self.samples[-1] if self.samples else None
        if previous and at <= previous["at"]:
            return False
        if previous:
            dt, delta = at - previous["at"], km - previous["km"]
            # Reject source disagreement and impossible jumps without poisoning
            # the baseline. A real odometer reset requires a new bike identity.
            if delta < -0.01 or delta > max(2, dt / 3600 * 80):
                return False
            if self.active and battery is not None and previous.get("battery") is not None and battery > previous["battery"] + 1:
                self.active["start_battery"] = None
                self.active["battery_drop"] = None
            if delta > 0.01:
                if self.active and at - self.active["last_move"] > 1800:
                    self.finish()
                if self.active is None:
                    self.active = {"start": previous["at"], "end": at,
                                   "start_km": previous["km"], "km": 0,
                                   "start_battery": previous.get("battery"),
                                   "battery_drop": None, "last_move": at,
                                   "quality": "interval" if dt > 21600 else "inferred"}
                self.active.update(end=at, last_move=at, km=round(km - self.active["start_km"], 3))
                start = self.active.get("start_battery")
                # Charging during an interval makes net consumption misleading.
                if battery is not None and previous.get("battery") is not None and battery > previous["battery"] + 1:
                    self.active["start_battery"] = None
                    start = None
                self.active["battery_drop"] = (round(start - battery, 2)
                                                if self.active["quality"] == "inferred" and start is not None and battery is not None and battery <= start else None)
            elif self.active and at - self.active["last_move"] >= 900:
                self.finish()
        # Compact repeated parked readings; otherwise a 2-minute poll would
        # evict a month's history after only two weeks.
        if previous and km == previous["km"] and battery == previous.get("battery") and at - previous["at"] < 3600:
            return True
        self.samples.append({"at": at, "km": km, "battery": battery, "source": source})
        self.samples = [s for s in self.samples if s["at"] >= at - 90 * DAY][-10000:]
        return True

    def finish(self):
        if self.active and self.active.get("km", 0) > 0:
            r = dict(self.active)
            drop = r.get("battery_drop")
            r["battery_pct_per_km"] = round(drop / r["km"], 3) if drop is not None else None
            self.rides.append(r)
            self.rides = self.rides[-1000:]
        self.active = None

    def summary(self, remaining_km=None, *, now):
        window = [s for s in self.samples if now - 28 * DAY <= s["at"] <= now]
        rides = [r for r in self.rides if r.get("end", 0) >= now - 28 * DAY]
        if self.active:
            rides = rides + [self.active]
        out = {"service_days": None, "service_weeks": None, "service_date": None,
               "service_rides": None, "km_per_day": None, "km_per_ride": None,
               "rides_per_week": None, "history_days": 0, "observed_rides": len(rides),
               "forecast_status": "insufficient_history", "method": "odometer_history_28d",
               "ride_quality": "inferred; long gaps may contain multiple rides",
               "last_ride": self.rides[-1] if self.rides else None,
               "rides": self.rides[-50:]}
        if rides:
            mean = sum(r["km"] for r in rides) / len(rides)
            out["km_per_ride"] = round(mean, 2)
        remaining = number(remaining_km)
        if remaining is not None and remaining <= 0:
            out.update(service_days=0, service_weeks=0, service_rides=0,
                       service_date=datetime.fromtimestamp(now, timezone.utc).date().isoformat(),
                       forecast_status="due")
            return out
        if len(window) < 2:
            return out
        days = (now - window[0]["at"]) / DAY
        out["history_days"] = round(days, 1)
        # Never stretch one very old reading into a current usage forecast.
        if now - window[-1]["at"] > 7 * DAY:
            out["forecast_status"] = "stale_history"
            return out
        if days < 7 or len(rides) < 3:
            return out
        distance = window[-1]["km"] - window[0]["km"]
        if distance <= 0:
            out["forecast_status"] = "no_usage"
            return out
        daily = distance / days  # calendar days include rest days
        out.update(km_per_day=round(daily, 3), rides_per_week=round(len(rides) / days * 7, 2))
        if remaining is None:
            out["forecast_status"] = "no_service_target"
            return out
        forecast = remaining / daily
        out.update(service_days=round(forecast, 1), service_weeks=round(forecast / 7, 1),
                   service_rides=round(remaining / out["km_per_ride"], 1) if out["km_per_ride"] else None,
                   forecast_status="estimated")
        if forecast <= 3650:
            out["service_date"] = datetime.fromtimestamp(now + forecast * DAY, timezone.utc).date().isoformat()
        return out
