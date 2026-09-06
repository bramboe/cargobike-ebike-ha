#!/usr/bin/env python3
"""Read-only PON.Bike history probe — shows recent movement/location so we can see
a movement event (e.g. a "bike moved" alert) that predates the add-on connecting.

Runs on your machine; your refresh token never leaves it. Read-only (GET only) —
it never reports anything. Stdlib only (certifi-aware SSL).

USAGE:
    python3 pon_probe.py <CLIENT_ID> [MINUTES]     # default 60 minutes back
    # then paste your PON refresh token when prompted (input hidden)
"""
import getpass
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request

TOKEN_URL = "https://consumer.login.pon.bike/oauth/token"
API = "https://data-act.connected.pon.bike/api"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _get(url, hdr):
    req = urllib.request.Request(url)
    for k, v in hdr.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, f"<{type(e).__name__}: {e}>"


def main() -> int:
    client_id = sys.argv[1] if len(sys.argv) > 1 else input("PON Client-ID: ").strip()
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    refresh = getpass.getpass("PON refresh token (hidden): ").strip()
    if not client_id or not refresh:
        print("client_id and refresh token required", file=sys.stderr)
        return 2

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": refresh}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
            tok = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print("token refresh failed:", e.code, e.read().decode()[:200], file=sys.stderr)
        return 1
    hdr = {"Authorization": "Bearer " + tok["access_token"],
           "Accept": "application/json"}
    print("token refresh: 200")

    s, info = _get(API + "/v1/bikes/info", hdr)
    bike = info[0].get("bikeId") if (s == 200 and isinstance(info, list) and info) else None
    print("bikes/info:", s, "bikeId:", bike)

    s, lk = _get(API + "/v1/bikes/last-known-states", hdr)
    if s == 200 and lk:
        e = lk[0] if isinstance(lk, list) else lk
        loc = (e.get("location") or {}).get("coordinate") or {}
        print("last-known:", "lastOnline=", e.get("lastOnline"),
              "lat=", loc.get("latitude"), "lon=", loc.get("longitude"),
              "odo=", e.get("odometer"))

    if not bike:
        return 0
    frm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes * 60))
    to = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"\n== TELEMETRY/history last {minutes} min ==")
    s, hist = _get(f"{API}/v1/bikes/{bike}/TELEMETRY/history"
                   f"?from={frm}&to={to}&offset=0&limit=500", hdr)
    items = hist.get("items") if isinstance(hist, dict) else None
    if isinstance(items, list):
        print("   samples:", len(items))
        moving = [it for it in items if isinstance(it, dict)
                  and (it.get("speedInKmh") or 0) > 0]
        print("   samples with speed>0 (movement):", len(moving))
        for it in moving[:20]:
            loc = it.get("location") or it.get("coordinate") or {}
            print("   ", it.get("timestamp"), "speed=", it.get("speedInKmh"),
                  ("lat=%s lon=%s" % (loc.get("latitude"), loc.get("longitude"))
                   if loc else ""))
        if not moving and items:
            print("   (no movement samples; newest sample keys:",
                  sorted(items[-1])[:12], ")")
    else:
        print("   status:", s, hist)
    print("\nDone. Read-only. Paste the output back (no token in it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
