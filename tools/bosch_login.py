#!/usr/bin/env python3
"""One-time Bosch SingleKey ID login → refresh_token for the eBike add-on.

Bosch's Data Act API (api.bosch-ebike.com) is OAuth2 authorization-code + PKCE
against the SingleKey ID Keycloak realm. The add-on itself only ever does the
refresh-token grant; this script does the interactive part once and hands you a
refresh_token to paste into the add-on options (bosch_refresh_token).

PREREQUISITES (you must do these — they can't be automated):
  1. Register a "Data Act" app at https://portal.bosch-ebike.com/data-act/app
     while logged in with your SingleKey ID. You get a Client-ID.
  2. In that app registration, add this exact redirect URI:
         http://localhost:8888/callback
  3. Your eBike must be visible in the Bosch eBike Flow app under that SingleKey ID.

USAGE:
    python3 bosch_login.py                # prompts for the Client-ID
    python3 bosch_login.py <CLIENT_ID>

It opens your browser to the Bosch login, catches the redirect on localhost:8888,
exchanges the code, and prints your refresh_token. Stdlib only — no pip installs.
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
import webbrowser


def _ssl_context() -> ssl.SSLContext:
    """A cert-verifying SSL context that works on the python.org macOS build too.

    That build ignores the system keychain, so a plain urlopen fails with
    'unable to get local issuer certificate'. Prefer certifi's CA bundle when it
    is installed; otherwise fall back to the default context (fine on Linux / the
    add-on container). We never disable verification — the response carries the
    refresh token, so an unverified TLS channel would be a real MITM risk."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()

AUTH_BASE = "https://p9.authz.bosch.com/auth/realms/obc/protocol/openid-connect"
AUTH_URL = f"{AUTH_BASE}/auth"
TOKEN_URL = f"{AUTH_BASE}/token"
REDIRECT_URI = "http://localhost:8888/callback"
PORT = 8888

_code_holder = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        code = (params.get("code") or [None])[0]
        _code_holder["code"] = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<h2>Bosch login complete.</h2>You can close this tab and return "
               "to the terminal.") if code else "<h2>No code received.</h2>"
        self.wfile.write(msg.encode())

    def log_message(self, *_a):  # silence the default request logging
        pass


def main() -> int:
    client_id = (sys.argv[1] if len(sys.argv) > 1
                 else input("Bosch Data Act Client-ID: ").strip())
    if not client_id:
        print("No Client-ID given.", file=sys.stderr)
        return 2

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    authorize = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "openid",
    })

    print("\nOpening your browser to sign in with your SingleKey ID…")
    print("If it doesn't open, paste this URL manually:\n\n  " + authorize + "\n")
    try:
        webbrowser.open(authorize)
    except Exception:  # noqa: BLE001
        pass

    print(f"Waiting for the redirect on {REDIRECT_URI} …")
    with http.server.HTTPServer(("localhost", PORT), _Handler) as httpd:
        httpd.handle_request()  # serve exactly one request (the callback)

    code = _code_holder.get("code")
    if not code:
        print("Login failed: no authorization code in the redirect.", file=sys.stderr)
        return 1

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            tokens = json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        print(f"Token exchange failed ({err.code}): {err.read().decode()}",
              file=sys.stderr)
        return 1

    rt = tokens.get("refresh_token")
    if not rt:
        print("No refresh_token in the response:\n" + json.dumps(tokens, indent=2),
              file=sys.stderr)
        return 1

    print("\n" + "=" * 68)
    print("SUCCESS — paste this into the add-on option 'bosch_refresh_token':\n")
    print(rt)
    print("\nAnd put your Client-ID in 'bosch_client_id'.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
