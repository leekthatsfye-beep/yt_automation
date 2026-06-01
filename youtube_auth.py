"""
youtube_auth.py

OAuth 2.0 Desktop flow for YouTube Data API v3.
Supports quota rotation across multiple Google Cloud projects.

Project 1: client_secret.json   → token.json
Project 2: client_secret_2.json → token_2.json
Project 3: client_secret_3.json → token_3.json
Project 4: client_secret_4.json → token_4.json
Project 5: client_secret_5.json → token_5.json

When a project hits quota (403 quotaExceeded), automatically
falls back to the next project. Total: ~50k units/day (~30 uploads).

Usage:
    from youtube_auth import get_youtube_service
    youtube = get_youtube_service()
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT   = Path(__file__).resolve().parent
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Project slots: (client_secret, token_file)
_PROJECTS = [
    (ROOT / "client_secret.json",   ROOT / "token.json"),
    (ROOT / "client_secret_2.json", ROOT / "token_2.json"),
    (ROOT / "client_secret_3.json", ROOT / "token_3.json"),
    (ROOT / "client_secret_4.json", ROOT / "token_4.json"),
    (ROOT / "client_secret_5.json", ROOT / "token_5.json"),
]

# Track which project is active this session
_active_project = 0


def _build_service(client_secret: Path, token_file: Path):
    """Authenticate and build a YouTube service for a given project slot."""
    if not client_secret.exists():
        raise FileNotFoundError(
            f"Missing {client_secret.name} — download from "
            "Google Cloud Console > APIs & Services > Credentials"
        )

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)

        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def get_youtube_service(force_project: int = None):
    """
    Returns an authenticated YouTube Data API v3 client.
    Uses the active project slot, auto-rotates on quota errors.

    Args:
        force_project: 0 or 1 to force a specific project slot.
    """
    global _active_project

    if force_project is not None:
        _active_project = force_project

    client_secret, token_file = _PROJECTS[_active_project]
    print(f"  [AUTH] Using project slot {_active_project + 1} ({client_secret.name})")
    return _build_service(client_secret, token_file)


def get_youtube_service_with_fallback():
    """
    Returns a YouTube service that auto-rotates to project 2 if project 1 hits quota.
    Use this for bulk operations like fix_descriptions.py.
    """
    global _active_project

    for slot in range(len(_PROJECTS)):
        _active_project = slot
        client_secret, token_file = _PROJECTS[slot]
        if not client_secret.exists():
            continue
        try:
            svc = _build_service(client_secret, token_file)
            # Quick sanity check — costs 1 unit
            svc.channels().list(part="id", mine=True, maxResults=1).execute()
            print(f"  [AUTH] Project slot {slot + 1} active ✓")
            return svc
        except HttpError as e:
            if "quotaExceeded" in str(e):
                print(f"  [AUTH] Project slot {slot + 1} quota exceeded — trying next...")
                continue
            raise

    raise RuntimeError("All Google Cloud project slots have exceeded quota. Try again tomorrow.")
