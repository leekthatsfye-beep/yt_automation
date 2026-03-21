"""
ig_auth.py

OAuth 2.0 token management for Instagram Graph API (via Facebook).
Reads IG_APP_ID and IG_APP_SECRET from environment.
Stores/reuses token in ig_token.json.

Requires an Instagram Business or Creator account linked to a Facebook Page.

Usage:
    from ig_auth import get_access_token
    access_token, ig_user_id = get_access_token()
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

log = logging.getLogger(__name__)

ROOT       = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "ig_token.json"

AUTH_URL   = "https://www.facebook.com/v22.0/dialog/oauth"
TOKEN_URL  = "https://graph.facebook.com/v22.0/oauth/access_token"
GRAPH_BASE = "https://graph.facebook.com/v22.0"
SCOPES     = "instagram_basic,instagram_content_publish,pages_read_engagement,pages_show_list"
REDIRECT_URI = "https://leekthatsfye-beep.github.io/ig-callback"


def _get_app_id() -> str:
    app_id = os.environ.get("IG_APP_ID", "")
    if not app_id:
        raise RuntimeError(
            "IG_APP_ID not set in environment. "
            "Add it to your .env file. Get it from developers.facebook.com"
        )
    return app_id


def _get_app_secret() -> str:
    secret = os.environ.get("IG_APP_SECRET", "")
    if not secret:
        raise RuntimeError(
            "IG_APP_SECRET not set in environment. "
            "Add it to your .env file. Get it from developers.facebook.com"
        )
    return secret


# ── Token persistence ─────────────────────────────────────────────────────────

def load_token() -> dict | None:
    """Load token data from ig_token.json, or None if missing/corrupt."""
    try:
        if TOKEN_FILE.exists() and TOKEN_FILE.stat().st_size > 0:
            return json.loads(TOKEN_FILE.read_text())
    except Exception:
        pass
    return None


def save_token(token_data: dict):
    """Save token data to ig_token.json."""
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2, default=str))
    log.info("Instagram token saved to %s", TOKEN_FILE.name)


def is_token_valid() -> bool:
    """Check if access_token exists and hasn't expired."""
    token = load_token()
    if not token or not token.get("access_token"):
        return False
    if not token.get("ig_user_id"):
        return False
    expires_at = token.get("expires_at", 0)
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at).timestamp()
        except Exception:
            return False
    # Valid if more than 1 day until expiry
    return time.time() < (expires_at - 86400)


# ── OAuth flow ────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    """Build the Facebook OAuth authorization URL for Instagram permissions."""
    params = {
        "client_id": _get_app_id(),
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code",
        "state": "ig_auth",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def run_local_callback_server(port: int = 8586, timeout: int = 300) -> str:
    """
    Start a temporary HTTP server to capture the Facebook OAuth callback.
    Returns the authorization code.
    """
    result = {"code": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            if code:
                result["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Instagram connected!</h1>"
                    b"<p>You can close this tab and return to Telegram.</p>"
                    b"</body></html>"
                )
            else:
                error = params.get("error_reason", ["unknown"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    f"<html><body><h1>Error: {error}</h1></body></html>".encode()
                )

        def log_message(self, format, *args):
            pass

    import ssl
    server = HTTPServer(("localhost", port), CallbackHandler)
    cert_file = ROOT / "localhost.crt"
    key_file = ROOT / "localhost.key"
    if cert_file.exists() and key_file.exists():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_file), str(key_file))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        log.info("HTTPS enabled for OAuth callback server")
    server.timeout = timeout

    log.info("Waiting for Instagram OAuth callback on port %d...", port)
    start = time.time()
    while result["code"] is None and (time.time() - start) < timeout:
        server.handle_request()

    server.server_close()

    if not result["code"]:
        raise RuntimeError("Instagram OAuth callback timed out")

    return result["code"]


def exchange_code(code: str) -> dict:
    """
    Exchange authorization code for tokens.
    1. Get short-lived token
    2. Exchange for long-lived token (60 days)
    3. Discover IG business account ID
    """
    app_id = _get_app_id()
    app_secret = _get_app_secret()

    # Step 1: Exchange code for short-lived token
    resp = requests.get(TOKEN_URL, params={
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "client_secret": app_secret,
        "code": code,
    }, timeout=15)
    resp.raise_for_status()
    short_data = resp.json()

    short_token = short_data.get("access_token")
    if not short_token:
        raise RuntimeError(f"FB code exchange failed: {json.dumps(short_data)}")

    # Step 2: Exchange short-lived for long-lived token
    resp = requests.get(TOKEN_URL, params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }, timeout=15)
    resp.raise_for_status()
    long_data = resp.json()

    long_token = long_data.get("access_token")
    expires_in = long_data.get("expires_in", 5184000)  # default 60 days

    if not long_token:
        raise RuntimeError(f"FB long-lived token exchange failed: {json.dumps(long_data)}")

    # Step 3: Discover IG business account
    ig_user_id, page_id, fb_user_id, page_token = _discover_ig_account(long_token)

    # Use the Page token for Content Publishing (more reliable than user token)
    # Page tokens from /me/accounts are long-lived when the user token is long-lived
    token_data = {
        "access_token": page_token,
        "user_token": long_token,
        "token_type": "long_lived",
        "expires_at": datetime.fromtimestamp(
            time.time() + expires_in, tz=timezone.utc
        ).isoformat(),
        "ig_user_id": ig_user_id,
        "page_id": page_id,
        "fb_user_id": fb_user_id,
    }
    save_token(token_data)
    log.info("Saved IG token: type=%s ig_user=%s page=%s",
             "page" if page_token != long_token else "user",
             ig_user_id, page_id)
    return token_data


def _discover_ig_account(access_token: str) -> tuple[str, str, str, str]:
    """
    Discover the Instagram Business account linked to user's Facebook Pages.
    Returns (ig_user_id, page_id, fb_user_id, page_access_token).
    """
    # Get user info
    me_resp = requests.get(f"{GRAPH_BASE}/me", params={
        "access_token": access_token,
    }, timeout=15)
    me_resp.raise_for_status()
    fb_user_id = me_resp.json().get("id", "")

    # Get user's pages
    pages_resp = requests.get(f"{GRAPH_BASE}/me/accounts", params={
        "access_token": access_token,
    }, timeout=15)
    pages_resp.raise_for_status()
    pages = pages_resp.json().get("data", [])

    if not pages:
        raise RuntimeError(
            "No Facebook Pages found. Instagram Business/Creator accounts "
            "must be linked to a Facebook Page. Create a Page first at "
            "facebook.com/pages/create"
        )

    log.info("Found %d Facebook Page(s) for user %s", len(pages), fb_user_id)

    # Check each page for an Instagram business account
    page_names = []
    for page in pages:
        page_id = page["id"]
        page_name = page.get("name", "unnamed")
        page_token = page.get("access_token", access_token)
        page_names.append(f"{page_name} ({page_id})")
        log.info("Checking page '%s' (ID: %s) for IG business account...", page_name, page_id)

        ig_resp = requests.get(f"{GRAPH_BASE}/{page_id}", params={
            "fields": "instagram_business_account,name",
            "access_token": page_token,
        }, timeout=15)
        ig_resp.raise_for_status()
        ig_data = ig_resp.json()
        log.info("  Page '%s' IG data: %s", page_name, json.dumps(ig_data))

        ig_account = ig_data.get("instagram_business_account", {})
        ig_user_id = ig_account.get("id")
        if ig_user_id:
            log.info("Found IG business account: %s (page: %s '%s')", ig_user_id, page_id, page_name)
            return ig_user_id, page_id, fb_user_id, page_token

    raise RuntimeError(
        f"None of your {len(pages)} Facebook Page(s) have a linked Instagram "
        f"Business/Creator account. Pages found: {', '.join(page_names)}. "
        f"Fix: Open Instagram app → Settings → Account → Switch to "
        f"Professional Account → connect it to one of these Facebook Pages."
    )


def refresh_long_token() -> str:
    """Refresh a long-lived token before it expires."""
    token = load_token()
    if not token or not token.get("access_token"):
        raise RuntimeError(
            "No Instagram token found. Run /ig_setup to authorize."
        )

    # Use user_token for refresh if available (Facebook Page flow)
    refresh_token = token.get("user_token") or token["access_token"]

    if refresh_token.startswith("IGAA"):
        # Instagram-native token — use IG refresh endpoint
        resp = requests.get("https://graph.instagram.com/refresh_access_token", params={
            "grant_type": "ig_refresh_token",
            "access_token": refresh_token,
        }, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"IG token refresh failed ({resp.status_code}). Run /ig_setup to re-authorize.")
    else:
        # Facebook Page token — use FB exchange endpoint with user token
        resp = requests.get(TOKEN_URL, params={
            "grant_type": "fb_exchange_token",
            "client_id": _get_app_id(),
            "client_secret": _get_app_secret(),
            "fb_exchange_token": refresh_token,
        }, timeout=15)
        resp.raise_for_status()

    data = resp.json()

    new_token = data.get("access_token")
    if not new_token:
        raise RuntimeError(f"IG token refresh failed: {json.dumps(data)}")

    # If we refreshed the user token, re-discover the page token
    if token.get("user_token") and not new_token.startswith("IGAA"):
        token["user_token"] = new_token
        # Page tokens derived from long-lived user tokens are also long-lived
        # Re-fetch page token via /me/accounts
        try:
            ig_user_id, page_id, fb_user_id, page_token = _discover_ig_account(new_token)
            token["access_token"] = page_token
            token["page_id"] = page_id
            token["fb_user_id"] = fb_user_id
        except Exception as e:
            log.warning("Page token refresh failed, using user token: %s", e)
            token["access_token"] = new_token
    else:
        token["access_token"] = new_token

    token["expires_at"] = datetime.fromtimestamp(
        time.time() + data.get("expires_in", 5184000), tz=timezone.utc
    ).isoformat()
    save_token(token)
    log.info("Instagram long-lived token refreshed")
    return token["access_token"]


# ── Main entry point ──────────────────────────────────────────────────────────

def get_access_token() -> tuple[str, str]:
    """
    Get a valid Instagram access token and IG user ID.
    Refreshes proactively when within 7 days of expiry.
    Returns (access_token, ig_user_id).
    """
    token = load_token()
    if not token or not token.get("access_token") or not token.get("ig_user_id"):
        raise RuntimeError(
            "No Instagram token found. Run /ig_setup in the bot to connect."
        )

    # Check if we need to refresh (within 7 days of expiry)
    expires_at = token.get("expires_at", "")
    needs_refresh = False
    if expires_at:
        try:
            exp_ts = datetime.fromisoformat(expires_at).timestamp()
            if time.time() > (exp_ts - 7 * 86400):
                needs_refresh = True
        except Exception:
            needs_refresh = True
    else:
        needs_refresh = True

    if needs_refresh:
        try:
            new_token = refresh_long_token()
            return new_token, token["ig_user_id"]
        except Exception as e:
            log.warning("IG token refresh failed: %s", e)
            # If still valid (just couldn't refresh), use current
            if is_token_valid():
                return token["access_token"], token["ig_user_id"]
            raise RuntimeError(
                "Instagram token expired and refresh failed. "
                "Run /ig_setup to re-authorize."
            ) from e

    return token["access_token"], token["ig_user_id"]
