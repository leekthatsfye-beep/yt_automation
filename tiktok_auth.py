"""
tiktok_auth.py

OAuth 2.0 token management for TikTok Content Posting API.
Reads TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET from environment.
Stores/reuses token in tiktok_token.json.

Usage:
    from tiktok_auth import get_access_token
    token = get_access_token()
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

ROOT       = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "tiktok_token.json"

AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL  = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES     = "user.info.basic,video.publish,video.upload"
REDIRECT_URI = "https://leekthatsfye-beep.github.io/tt-callback/"


def _get_client_key() -> str:
    key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    if not key:
        raise RuntimeError(
            "TIKTOK_CLIENT_KEY not set in environment. "
            "Add it to your .env file. Get it from developers.tiktok.com"
        )
    return key


def _get_client_secret() -> str:
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "TIKTOK_CLIENT_SECRET not set in environment. "
            "Add it to your .env file. Get it from developers.tiktok.com"
        )
    return secret


# ── Token persistence ─────────────────────────────────────────────────────────

def load_token() -> dict | None:
    """Load token data from tiktok_token.json, or None if missing/corrupt."""
    try:
        if TOKEN_FILE.exists() and TOKEN_FILE.stat().st_size > 0:
            return json.loads(TOKEN_FILE.read_text())
    except Exception:
        pass
    return None


def save_token(token_data: dict):
    """Save token data to tiktok_token.json."""
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2, default=str))
    log.info("TikTok token saved to %s", TOKEN_FILE.name)


def is_token_valid() -> bool:
    """Check if access_token exists and hasn't expired."""
    token = load_token()
    if not token or not token.get("access_token"):
        return False
    expires_at = token.get("expires_at", 0)
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at).timestamp()
        except Exception:
            return False
    # Valid if more than 60 seconds until expiry
    return time.time() < (expires_at - 60)


# ── OAuth flow ────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    """Build the TikTok OAuth authorization URL."""
    state = secrets.token_urlsafe(16)
    params = {
        "client_key": _get_client_key(),
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for access_token + refresh_token."""
    body = {
        "client_key": _get_client_key(),
        "client_secret": _get_client_secret(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    resp = requests.post(TOKEN_URL, data=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"TikTok token exchange failed: {json.dumps(data)}")

    token_data = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": datetime.fromtimestamp(
            time.time() + data.get("expires_in", 86400), tz=timezone.utc
        ).isoformat(),
        "open_id": data.get("open_id", ""),
        "scope": data.get("scope", SCOPES),
        "refresh_expires_at": datetime.fromtimestamp(
            time.time() + data.get("refresh_expires_in", 365 * 86400),
            tz=timezone.utc,
        ).isoformat(),
    }
    save_token(token_data)
    return token_data


def refresh_access_token() -> str:
    """Refresh the access_token using the refresh_token."""
    token = load_token()
    if not token or not token.get("refresh_token"):
        raise RuntimeError(
            "No TikTok refresh token found. Run /tiktok_setup to re-authorize."
        )

    body = {
        "client_key": _get_client_key(),
        "client_secret": _get_client_secret(),
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
    }

    resp = requests.post(TOKEN_URL, data=body, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {json.dumps(data)}")

    token["access_token"] = data["access_token"]
    token["expires_at"] = datetime.fromtimestamp(
        time.time() + data.get("expires_in", 86400), tz=timezone.utc
    ).isoformat()
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    if data.get("refresh_expires_in"):
        token["refresh_expires_at"] = datetime.fromtimestamp(
            time.time() + data["refresh_expires_in"], tz=timezone.utc
        ).isoformat()

    save_token(token)
    log.info("TikTok access token refreshed")
    return token["access_token"]


# ── Main entry point ──────────────────────────────────────────────────────────

def get_access_token() -> str:
    """
    Get a valid TikTok access token.
    Refreshes if expired. Raises if no token at all.
    """
    if is_token_valid():
        token = load_token()
        return token["access_token"]

    # Try to refresh
    token = load_token()
    if token and token.get("refresh_token"):
        try:
            return refresh_access_token()
        except Exception as e:
            log.warning("TikTok token refresh failed: %s", e)

    raise RuntimeError(
        "No valid TikTok token. Run /tiktok in the bot to connect your TikTok account."
    )
