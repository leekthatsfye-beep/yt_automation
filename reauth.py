"""
Quick re-authentication script.
Uses fixed port 8085, does NOT auto-open browser.
Navigate to the printed URL manually.
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT          = Path(__file__).resolve().parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_FILE    = ROOT / "token.json"
SCOPES        = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

print("Starting YouTube OAuth flow on port 8085...")
print("Navigate to the URL that appears below in your browser.\n")

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
creds = flow.run_local_server(port=8085, open_browser=True)

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

# Quick sanity check
yt = build("youtube", "v3", credentials=creds)
ch = yt.channels().list(part="snippet", mine=True).execute()
title = ch["items"][0]["snippet"]["title"] if ch.get("items") else "unknown"
print(f"\nAuthenticated as: {title}")
print("token.json saved. You can now run upload.py normally.")
