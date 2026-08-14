"""
setup_slots.py — manage the multi-project YouTube API quota slots.

youtube_auth.py rotates across 5 Google Cloud project slots:
    client_secret.json    -> token.json      (slot 1)
    client_secret_2.json  -> token_2.json    (slot 2)
    ...                                       (up to slot 5)

Quota is billed PER GOOGLE CLOUD PROJECT, so two OAuth clients from the same
project share one 10k/day pool and buy nothing. This script enforces that:
installs are refused when the project_id already occupies a slot.

Usage:
  python scripts/setup_slots.py --status
  python scripts/setup_slots.py --scan
  python scripts/setup_slots.py --install "C:\\path\\to\\client_secret_x.json"
  python scripts/setup_slots.py --install "...json" --slot 3 --force
  python scripts/setup_slots.py --auth            # consent for every slot missing a token
  python scripts/setup_slots.py --auth --slot 2   # consent for one slot
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.auth.transport.requests import Request           # noqa: E402
from google.oauth2.credentials import Credentials            # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow       # noqa: E402
from googleapiclient.discovery import build                  # noqa: E402
from googleapiclient.errors import HttpError                 # noqa: E402

from youtube_auth import _PROJECTS, SCOPES                   # noqa: E402

SCAN_DIRS = [
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Dropbox",
    ROOT,
]


# ── helpers ──────────────────────────────────────────────────────────────

def read_client(path: Path) -> dict | None:
    """Return {project_id, client_id, kind} for an OAuth client JSON, else None."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    for kind in ("installed", "web"):
        if kind in data and "client_id" in data[kind]:
            c = data[kind]
            return {
                "kind": kind,
                "project_id": c.get("project_id", "?"),
                "client_id": c.get("client_id", ""),
            }
    return None


def load_creds(token_file: Path) -> Credentials | None:
    if not token_file.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(token_file), SCOPES)
    except Exception:
        return None


def probe(creds: Credentials) -> str:
    """One-unit sanity call. Quota errors still prove the token is good."""
    try:
        yt = build("youtube", "v3", credentials=creds)
        r = yt.channels().list(part="snippet", mine=True, maxResults=1).execute()
        items = r.get("items") or []
        name = items[0]["snippet"]["title"] if items else "?"
        return f"OK ({name})"
    except HttpError as e:
        if "quotaExceeded" in str(e):
            return "OK (quota exhausted today)"
        return f"HTTP error: {str(e)[:60]}"
    except Exception as e:
        if "invalid_grant" in str(e):
            return "EXPIRED/REVOKED — needs --auth"
        return f"error: {str(e)[:60]}"


# ── commands ─────────────────────────────────────────────────────────────

def cmd_status(deep: bool = True) -> None:
    print(f"\n  Quota slots in {ROOT}\n")
    print(f"  {'#':<3}{'client_secret':<24}{'project_id':<28}{'token':<8}status")
    print("  " + "─" * 88)
    for i, (cs, tok) in enumerate(_PROJECTS, start=1):
        if not cs.exists():
            print(f"  {i:<3}{cs.name:<24}{'— empty —':<28}{'—':<8}download a client from a NEW project")
            continue
        info = read_client(cs) or {"project_id": "unreadable", "client_id": ""}
        creds = load_creds(tok)
        if creds is None:
            state = "no token — run --auth"
            tokmark = "no"
        else:
            tokmark = "yes"
            if creds.valid:
                state = probe(creds) if deep else "token valid"
            elif creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    tok.write_text(creds.to_json(), encoding="utf-8")
                    state = "refreshed ✓ " + (probe(creds) if deep else "")
                except Exception as e:
                    state = ("EXPIRED/REVOKED — needs --auth"
                             if "invalid_grant" in str(e) else f"refresh failed: {str(e)[:40]}")
            else:
                state = "invalid — run --auth"
        print(f"  {i:<3}{cs.name:<24}{info['project_id']:<28}{tokmark:<8}{state}")

    projects = {read_client(cs)["project_id"] for cs, _ in _PROJECTS
                if cs.exists() and read_client(cs)}
    print(f"\n  Distinct Cloud projects installed: {len(projects)}  "
          f"(~{len(projects) * 10_000:,} general quota units/day)\n")


def cmd_scan() -> None:
    installed = {}
    for i, (cs, _) in enumerate(_PROJECTS, start=1):
        info = read_client(cs) if cs.exists() else None
        if info:
            installed[info["project_id"]] = i

    print("\n  Scanning for OAuth client JSON files...\n")
    seen, found = set(), 0
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for path in sorted(d.glob("*.json")) + sorted(d.glob("*/*.json")):
            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            info = read_client(path)
            if not info:
                continue
            found += 1
            dup = installed.get(info["project_id"])
            note = (f"DUPLICATE of slot {dup} — same project, no extra quota"
                    if dup else "NEW project — install it")
            print(f"  {path}")
            print(f"      project: {info['project_id']:<28} {note}\n")
    if not found:
        print("  No OAuth client JSON files found in Downloads/Desktop/Dropbox.\n")


def cmd_install(src: str, slot: int | None, force: bool) -> None:
    src_path = Path(src).expanduser()
    if not src_path.exists():
        print(f"[FAIL] not found: {src_path}")
        sys.exit(1)
    info = read_client(src_path)
    if not info:
        print(f"[FAIL] {src_path.name} is not an OAuth client JSON "
              f"(no 'installed'/'web' section).")
        sys.exit(1)
    if info["kind"] != "installed":
        print(f"[WARN] client type is '{info['kind']}', expected 'installed' "
              f"(Desktop app). The consent flow may refuse it.")

    for i, (cs, _) in enumerate(_PROJECTS, start=1):
        if cs.exists():
            other = read_client(cs)
            if other and other["project_id"] == info["project_id"] and i != slot:
                if not force:
                    print(f"[FAIL] project '{info['project_id']}' is already slot {i}.")
                    print("       Same project = same 10k/day pool, so this adds NOTHING.")
                    print("       Create a NEW Cloud project and download its Desktop client,")
                    print("       or pass --force to install anyway.")
                    sys.exit(1)
                print(f"[WARN] duplicate of slot {i} — installing anyway (--force).")

    if slot is None:
        slot = next((i for i, (cs, _) in enumerate(_PROJECTS, start=1) if not cs.exists()), None)
        if slot is None:
            print("[FAIL] all 5 slots are full. Pass --slot N to overwrite one.")
            sys.exit(1)

    dst_cs, dst_tok = _PROJECTS[slot - 1]
    if dst_cs.exists():
        backup = dst_cs.with_suffix(".json.bak")
        shutil.copy2(dst_cs, backup)
        print(f"[BAK]  {dst_cs.name} → {backup.name}")
    shutil.copy2(src_path, dst_cs)
    if dst_tok.exists():
        dst_tok.unlink()          # old token belongs to the old client
        print(f"[DEL]  stale {dst_tok.name} removed")
    print(f"[OK]   slot {slot}: {info['project_id']} → {dst_cs.name}")
    print(f"       next: python scripts/setup_slots.py --auth --slot {slot}")


def cmd_auth(slot: int | None, port: int) -> None:
    targets = [slot] if slot else [
        i for i, (cs, tok) in enumerate(_PROJECTS, start=1)
        if cs.exists() and (load_creds(tok) is None or not load_creds(tok).valid)
    ]
    if not targets:
        print("[OK] every installed slot already has a valid token — nothing to do.")
        return

    for s in targets:
        cs, tok = _PROJECTS[s - 1]
        if not cs.exists():
            print(f"[SKIP] slot {s}: no {cs.name}")
            continue
        info = read_client(cs) or {"project_id": "?"}
        print(f"\n  ── slot {s} ({info['project_id']}) ─────────────────────────────")
        print("  A browser window will open. Sign in as the LEEKTHATSFY3 channel owner")
        print("  and approve. If Google warns 'unverified app', click Advanced → Continue.\n")
        if tok.exists():
            tok.replace(tok.with_suffix(".json.old"))
            print(f"  [BAK] previous {tok.name} → {tok.name.replace('.json', '.json.old')}")
        flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
        creds = flow.run_local_server(port=port, open_browser=True)
        tok.write_text(creds.to_json(), encoding="utf-8")
        print(f"  [OK] {tok.name} written — {probe(creds)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show every slot and its token state")
    ap.add_argument("--scan", action="store_true", help="find OAuth client JSONs on disk")
    ap.add_argument("--install", metavar="FILE", help="install an OAuth client JSON into a slot")
    ap.add_argument("--auth", action="store_true", help="run consent for slots without a valid token")
    ap.add_argument("--slot", type=int, choices=[1, 2, 3, 4, 5], help="target a specific slot")
    ap.add_argument("--force", action="store_true", help="allow installing a duplicate project")
    ap.add_argument("--port", type=int, default=0, help="local consent port (0 = random)")
    ap.add_argument("--shallow", action="store_true", help="--status without the 1-unit API probe")
    args = ap.parse_args()

    os.chdir(ROOT)

    if args.install:
        cmd_install(args.install, args.slot, args.force)
    elif args.auth:
        cmd_auth(args.slot, args.port)
    elif args.scan:
        cmd_scan()
    else:
        cmd_status(deep=not args.shallow)


if __name__ == "__main__":
    main()
