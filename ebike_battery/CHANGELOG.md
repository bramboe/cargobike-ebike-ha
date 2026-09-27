# Changelog

## 2.63.0 — passive anti-theft guard & cleanup

**Passive guard (no connection, no extra GPS-module battery)**
- While the alarm is armed, the alarm goes off as soon as the GPS module hasn't
  been heard for 5 minutes (setting `presence_alarm_minutes`, 1–60). This only
  listens for the module's Bluetooth advertisement and never connects to it.
- The alarm now carries a `reason` attribute (e.g. `presence`), so automations
  can send a different, urgent message when the bike is gone.
- New diagnostic sensor *Longest silence (24h)*: the longest normal gap between
  two sightings. Check it before you lower the delay.
- A restart no longer briefly reports the bike as *out of range*.
- If *Tracker motion* is off under Sensors, the panel shows "Passive guard"
  instead of the battery warning.

**Cleanup**
- Removed the one-off PON module-ID dump and the Bosch theft-log line.
- Removed the duplicate *Next service in* sensor. The Bosch cloud value remains.
- Removed `tools/pon_probe.py`. Reusing the add-on's PON token from outside the
  add-on could break it.

## 2.62.0 — stability & security review

**Ride detection works again**
- PON's `TELEMETRY/history` answers 403 for this app (no consent for that data), so
  speed was never available: *In use* never turned on, rides were never logged and
  the activity feed filled with "moved" every two minutes while riding. Riding is now
  detected from GPS movement between polls (with a red-light hysteresis, and parked
  at once when the tracker is heard at home). The measured speed is still used when
  telemetry is available.
- A refused (403) cloud endpoint is skipped with a backoff instead of being retried —
  with a token refresh — on every poll. One log line instead of one every 2 minutes.
- The cloud poll wakes up immediately when the bike is switched on, arrives or
  leaves (instead of waiting up to 30 minutes).

**Anti-theft reliability**
- The alarm is restored from the broker *after* connecting. Before, a slow broker
  (>2 s) could silently overwrite an armed state with "disarmed".
- A Bluetooth error while scanning for the tracker no longer stops the motion
  watcher for good; all background loops are supervised and restart on a crash.
- After a broker restart the alarm state is re-published.

**Robustness**
- MQTT connects in the background and keeps retrying — the add-on no longer exits
  when the broker isn't up yet (e.g. after a host reboot).
- Config, rotated cloud refresh tokens and history are written atomically (a power
  cut can no longer corrupt them or lose a token).
- MQTT messages are handled on the main loop (no cross-thread state changes).
- Failed bike reads back off instead of retrying every few seconds.
- Python dependencies are pinned, so an update never pulls a breaking new major.

**Security**
- The panel only accepts requests from Home Assistant's ingress (172.30.32.2).
- Names from nearby Bluetooth devices, HA entities and the cloud are HTML-escaped
  in the panel (they could otherwise inject script into Home Assistant's page).

**Quieter logs**
- Hourly "Bosch cloud"/"theft log" lines only when something changes; timeouts
  now say what happened instead of an empty message.
