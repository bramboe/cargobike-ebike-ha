#!/usr/bin/env python3
"""One-time PON.Bike (MyUrbanArrow) login -> refresh_token for the eBike add-on.

PON's Connected Bike / Data Act API (data-act.connected.pon.bike) authenticates
through Auth0 (consumer.login.pon.bike) with OAuth2 authorization-code + PKCE.
The add-on itself only does the refresh-token grant; this script does the
interactive part once and hands you a refresh_token for the add-on option
`pon_refresh_token` (put your app's Client-ID in `pon_client_id`).

PREREQUISITES (you do these — they can't be automated):
  1. Register a Data Act app at https://data-act.pon.bike while logged in with
     your MyUrbanArrow / PON account. You get a Client-ID (your "code").
  2. In that app registration, add this exact redirect URI:
         http://localhost:8888/callback
  3. Make it a public / PKCE client (no client secret), like the Bosch one.

USAGE:
    python3 pon_login.py <CLIENT_ID>
    python3 pon_login.py <CLIENT_ID> --audience <API_AUDIENCE>   # only if needed

It opens your browser to the PON login, catches the redirect on localhost:8888,
exchanges the code, then self-tests the token against the PON API and prints your
refresh_token. Stdlib only (certifi-aware SSL) — no pip installs.
"""
import base64
import hashlib
import http.server
import json
import secrets
import ssl
import sys
import urllib.parse
import urllib.request

AUTH_URL = "https://consumer.login.pon.bike/authorize"
TOKEN_URL = "https://consumer.login.pon.bike/oauth/token"
API_TEST = "https://data-act.connected.pon.bike/api/v1/bikes/info"
REDIRECT_URI = "http://localhost:8888/callback"
PORT = 8888
# offline_access is what makes Auth0 return a refresh token.
SCOPE = "openid offline_access"
# PON's Auth0 needs this API audience or the access token is login-only (API 401s).
AUDIENCE = "https://data-act.connected.pon.bike/"

_code_holder = {}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _code_holder["code"] = (params.get("code") or [None])[0]
        _code_holder["error"] = (params.get("error_description")
                                 or params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>PON login complete.</h2>You can close this tab and return "
               "to the terminal.") if _code_holder["code"] else "<h2>No code.</h2>"
        self.wfile.write(msg.encode())

    def log_message(self, *_a):
        pass


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
        return json.loads(r.read().decode())


def main() -> int:
    args = [a for a in sys.argv[1:]]
    audience = None
    if "--audience" in args:
        i = args.index("--audience")
        audience = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    client_id = args[0] if args else input("PON Data Act Client-ID: ").strip()
    if not client_id:
        print("No Client-ID given.", file=sys.stderr)
        return 2
    if audience is None:
        audience = AUDIENCE          # default to the known PON Data Act audience

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": SCOPE,
    }
    if audience:
        params["audience"] = audience
    authorize = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("\nOpening your browser to sign in with your MyUrbanArrow / PON account…")
    print("If it doesn't open, paste this URL manually:\n\n  " + authorize + "\n")
    try:
        import webbrowser
        webbrowser.open(authorize)
    except Exception:  # noqa: BLE001
        pass

    print(f"Waiting for the redirect on {REDIRECT_URI} …")
    with http.server.HTTPServer(("localhost", PORT), _Handler) as httpd:
        httpd.handle_request()
    if _code_holder.get("error"):
        print("Login error:", _code_holder["error"], file=sys.stderr)
    code = _code_holder.get("code")
    if not code:
        print("Login failed: no authorization code in the redirect.", file=sys.stderr)
        return 1

    try:
        tokens = _post(TOKEN_URL, {
            "grant_type": "authorization_code", "client_id": client_id,
            "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier})
    except urllib.error.HTTPError as err:
        print(f"Token exchange failed ({err.code}): {err.read().decode()[:300]}",
              file=sys.stderr)
        return 1

    rt = tokens.get("refresh_token")
    access = tokens.get("access_token")
    if not rt:
        print("No refresh_token returned. Make sure the app requests offline_access "
              "and is a public/PKCE client.\n" + json.dumps(tokens, indent=2)[:300],
              file=sys.stderr)
        return 1

    # Self-test: does this access token actually work against the PON API?
    print("\n== self-test: GET /v1/bikes/info ==")
    try:
        req = urllib.request.Request(API_TEST)
        req.add_header("Authorization", "Bearer " + access)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
            body = r.read().decode()
        print("   status: 200 — token works against the PON API")
        try:
            js = json.loads(body)
            n = len(js) if isinstance(js, list) else "?"
            print("   bikes:", n)
        except Exception:  # noqa: BLE001
            pass
    except urllib.error.HTTPError as err:
        print(f"   status: {err.code} — token did NOT work: {err.read().decode()[:200]}")
        print("   -> likely a missing 'audience'. Re-run with --audience <API id> "
              "(ask if unsure).")

    print("\n" + "=" * 68)
    print("SUCCESS — paste this into the add-on option 'pon_refresh_token':\n")
    print(rt)
    print("\nAnd put your Client-ID in 'pon_client_id'.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
