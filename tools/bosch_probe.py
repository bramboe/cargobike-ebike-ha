#!/usr/bin/env python3
"""Read-only diagnostic for the Bosch Data Act API — tells us WHY the add-on's
Bosch poll returns no data (scopes/subscription vs. empty vs. a parser mismatch).

Runs entirely on your machine; your refresh token never leaves it. It prints HTTP
statuses and which fields come back — not full dumps — so the output is safe to
paste back. Stdlib only (certifi-aware SSL, like bosch_login.py).

USAGE:
    python3 bosch_probe.py <CLIENT_ID>
    # then paste your refresh token when prompted (input is hidden)
"""
import getpass
import json
import ssl
import sys
import urllib.parse
import urllib.request

TOKEN_URL = ("https://p9.authz.bosch.com/auth/realms/obc/"
             "protocol/openid-connect/token")
API = "https://api.bosch-ebike.com"
BIKES = "/bike-profile/smart-system/v1/bikes"
SERVICE = "/service-book/smart-system/v1/service-records"
BIKEPASS = "/bike-pass/smart-system/v1/bike-passes"


def _ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _req(method, url, *, headers=None, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return None, f"<{type(e).__name__}: {e}>"


def _keys(txt):
    try:
        j = json.loads(txt)
    except Exception:  # noqa: BLE001
        return "<non-JSON>", None
    if isinstance(j, dict):
        return f"dict keys={sorted(j)[:12]}", j
    if isinstance(j, list):
        return f"list len={len(j)}", j
    return type(j).__name__, j


def main() -> int:
    client_id = sys.argv[1] if len(sys.argv) > 1 else input("Client-ID: ").strip()
    refresh = getpass.getpass("Refresh token (hidden): ").strip()
    if not client_id or not refresh:
        print("client_id and refresh token required", file=sys.stderr)
        return 2

    print("\n== 1. token refresh ==")
    s, body = _req("POST", TOKEN_URL, data={
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": refresh})
    print("   status:", s)
    if s != 200:
        print("   body:", body[:300])
        print("\n-> token refresh failed; fix client_id/token first.")
        return 1
    tok = json.loads(body)
    access = tok.get("access_token")
    print("   scopes granted:", tok.get("scope"))
    print("   expires_in:", tok.get("expires_in"))
    hdr = {"Authorization": "Bearer " + access, "Accept": "application/json"}

    print("\n== 2. GET", BIKES, "==")
    s, body = _req("GET", API + BIKES, headers=hdr)
    desc, j = _keys(body)
    print("   status:", s, "|", desc)
    bike_id = batt_serial = None
    if s == 200 and isinstance(j, dict):
        bikes = j.get("bikes") or []
        print("   bikes count:", len(bikes))
        if bikes:
            b = bikes[0]
            print("   bike[0] keys:", sorted(b)[:20])
            bike_id = b.get("bikeId") or b.get("id")
            drive = b.get("driveUnit") or {}
            print("   driveUnit keys:", sorted(drive)[:20] if drive else None)
            batt = b.get("battery") or (b.get("batteries") or [{}])[0]
            if isinstance(batt, dict):
                print("   battery keys:", sorted(batt)[:20])
                batt_serial = batt.get("serialNumber")
                print("   battery.chargeCycles:", batt.get("chargeCycles"))
                print("   battery.deliveredWhOverLifetime:",
                      batt.get("deliveredWhOverLifetime"))
                print("   battery.productName:", batt.get("productName"))
            print("   driveUnit.powerOnTime:", drive.get("powerOnTime"))
            print("   driveUnit.maximumAssistanceSpeed:",
                  drive.get("maximumAssistanceSpeed"))
            print("   driveUnit.odometer:", drive.get("odometer"))
            print("   serviceDue:", json.dumps(b.get("serviceDue")))
    elif s != 200:
        print("   body:", body[:400])

    if bike_id:
        print("\n== 3. GET", SERVICE, "==")
        s, body = _req("GET", f"{API}{SERVICE}?bikeId={bike_id}", headers=hdr)
        desc, j = _keys(body)
        print("   status:", s, "|", desc)
        if s == 200 and isinstance(j, dict):
            recs = j.get("serviceRecords") or j.get("records") or j.get("items") or []
            print("   record count:", len(recs) if isinstance(recs, list) else "?")
            types = sorted({r.get("type") for r in recs
                            if isinstance(r, dict) and r.get("type")}) \
                if isinstance(recs, list) else []
            print("   record types:", types)
            if isinstance(recs, list) and recs:
                print("   record[0] keys:", sorted(recs[0])[:15])
                print("   record[0]:", json.dumps(recs[0])[:400])
        elif s != 200:
            print("   body:", body[:400])

        print("\n== 4. GET", BIKEPASS, "==")
        s, body = _req("GET", f"{API}{BIKEPASS}?bikeId={bike_id}", headers=hdr)
        desc, j = _keys(body)
        print("   status:", s, "|", desc)
        if s == 200 and isinstance(j, dict):
            passes = j.get("bikePasses") or []
            print("   bikePasses count:", len(passes))
            if passes:
                print("   bikePass[0] keys:", sorted(passes[0])[:20])
        elif s != 200:
            print("   body:", body[:300])

    print("\nDone. Paste the section headers + statuses back (not the token).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
