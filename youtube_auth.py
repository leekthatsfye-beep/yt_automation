"""
youtube_auth.py

OAuth 2.0 Desktop flow for YouTube Data API v3.
Reads client_secret.json from project root.
Stores/reuses token in token.json.

Usage:
    from youtube_auth import get_youtube_service
    youtube = get_youtube_service()
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ROOT          = Path(__file__).resolve().parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_FILE    = ROOT / "token.json"
SCOPES        = [
    "https://www.googleapis.com/auth/youtube",           # full access (upload, delete, edit)
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # needed for /analytics
]


def get_youtube_service():
    """
    Returns an authenticated YouTube Data API v3 client.
    - If token.json exists and is valid, reuses it.
    - If expired and refreshable, refreshes silently.
    - Otherwise opens browser for OAuth consent.
    """
    if not CLIENT_SECRET.exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRET.name} — download it from "
            "Google Cloud Console > APIs & Services > Credentials > "
            "OAuth 2.0 Client IDs > Desktop app > Download JSON"
        )

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET), SCOPES
            )
            creds = flow.run_local_server(port=0, open_browser=True)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)
