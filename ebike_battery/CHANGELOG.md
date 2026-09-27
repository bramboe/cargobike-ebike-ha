# Changelog

## 2.67.0 — no more Bluetooth connection to the GPS module

**Removed: Bluetooth motion detection ("Tracker motion")**
Motion over Bluetooth needed a permanent connection to the GPS module, which
drained its battery. Two deliberate motion tests (27 Sep) confirmed that the
module's advertisement gives nothing away: content, rate and signal strength
stay the same while the bike is moved. So the add-on no longer connects to the
module for motion. It only connects briefly, when the bike is switched on, to
read the module's battery level.
- Removed the *Tracker motion* sensor row, the `tracker_always_on` and
  `probe_frames` options, and the low-module-battery auto-disarm (nothing drains
  the module any more).
- The *Motion* sensor still works for external sensors mounted on the bike.

**New: logging GPS module reports from the PON cloud (logging only)**
When moved, the module reports to the PON cloud on its own: new position and
state within about 30 s. While the alarm is armed the add-on now checks PON
every 30 s and logs every change (`PON module report`). This is logging only,
no alarm yet. The data shows how routine reports differ from reports caused by
movement.

## 2.66.0 — one motion test instead of two probes

- New developer option **Motion test** (`motion_test`), replacing *Advertisement
  probe* and *Hub wake-on-motion probe*. It never connects. It logs, all at once:
  - the GPS module's full advertisement, rate and signal strength every 10 s;
  - whether the Bosch hub starts advertising;
  - which fields of the PON cloud state change (polled every 30 s during the test).

  Rest, move the bike, rest, and compare the `MOTION TEST` log lines.

## 2.65.0 — 45-second guard, silence measured while armed

- The presence alarm now goes off after **45 s** by default (was 30). While
  armed that allows three missed scans in a row before a false alarm. A thief is
  about 40–60 m further away than at 30 s, and GPS tracks the bike from there.
- The *Longest silence while armed (24h)* sensor (was *Longest silence (24h)*)
  now only counts gaps measured while the alarm is armed. The slower disarmed
  scanning overstated the silences that cause false alarms. Rule of thumb: keep
  the delay at least 1.5× this value. It reads 0 until the alarm has been armed.

## 2.64.0 — 30-second guard, pauses while the bike is away

- **Alarm after 30 s instead of 5 min.** While armed, the add-on listens for the
  GPS module almost continuously (10 s scans, 2 s apart), so the alarm goes off
  about 30–45 s after the bike leaves. The option is now
  `presence_alarm_seconds` (15–3600, default 30). The extra listening uses Home
  Assistant's Bluetooth adapter, not the module battery.
- **Listening pauses while GPS says the bike is away.** If a recent PON GPS
  position puts the bike outside your home zone and Bluetooth can't hear it, the
  add-on stops scanning. It starts again as soon as GPS puts the bike home, or
  when the GPS position is more than 10 minutes old.
- Every Bluetooth scan the add-on makes now counts as hearing the module, not
  only the presence scan. A bike scan that keeps the adapter busy no longer
  looks like silence (which could have caused a false alarm at 30 s).

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
