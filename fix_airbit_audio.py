#!/usr/bin/env python3
"""
fix_airbit_audio.py
-------------------
Re-uploads the correct MP3 to each Airbit listing that has the wrong audio.

Uses the mismatch list from audit_airbit_audio.py --fast output, plus a
hardcoded list of known bad listings from the name-vs-filename audit.

Usage:
    python fix_airbit_audio.py              # fix all known mismatches
    python fix_airbit_audio.py --dry-run    # preview only
    python fix_airbit_audio.py --alias dopeman  # fix one listing by alias
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT      = Path(__file__).resolve().parent
BEATS_DIR = ROOT / "beats"
SESSION_F = ROOT / "airbit_session.json"
FIXED_LOG = ROOT / "airbit_audio_fixed.json"
AIRBIT_USER_ID = 455547
AIRBIT_BASE    = "https://api.airbit.com"
STORE_BASE     = "https://leekthatsfy3.infinity.airbit.com"

# ── Load credentials ──────────────────────────────────────────────────────────
def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_env()
AIRBIT_EMAIL    = os.environ.get("AIRBIT_EMAIL", "")
AIRBIT_PASSWORD = os.environ.get("AIRBIT_PASSWORD", "")

# ── Known mismatches from audit: alias → correct local stem ──────────────────
# These were identified by comparing listing names vs CDN filenames.
KNOWN_MISMATCHES = {
    "1017-1":          "1017",          # listing "1017!" was playing "grivley"
    "batttth-1":       "batttth",       # "batttth!" was playing "halow33n"
    "blatt":           "blatt",         # "blatt!" was playing "hendrix"
    "bolls-boyce":     "bolls_boyce",   # "bolls boyce!" was playing "grew_up"
    "doggy":           "doggy",         # was playing "candyman"
    "dopeman":         "dopeman",       # was playing "dopeboy"
    "finally":         "finally",       # was playing "living"
    "halow33n":        "halow33n",      # "halow33n!" was playing "batttth"
    "hot":             "hot",           # was playing "mop"
    "member":          "member",        # was playing "mamba"
    "muscle":          "muscle",        # was playing "grape"
    "rolls":           "rolls",         # was playing "audi"
    "st3ma":           "st3ma",         # was playing "steamer"
    "wokesha":         "wokesha",       # was playing "wockesha" (close enough)
    "zac-kodi":        "zac_kodi",      # "zac & kodi!" was playing "ebgd"
    "choppa":          "choppa",        # "choppa" was playing "chopa" (typo)
}


def safe_stem(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s


def fetch_beat_by_alias(alias: str) -> dict | None:
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": f"{STORE_BASE}/",
        "Origin": STORE_BASE,
    }
    # Fetch all and find by alias
    beats, page = [], 1
    while True:
        r = requests.get(
            f"{AIRBIT_BASE}/users/{AIRBIT_USER_ID}/beats",
            params={"limit": 50, "page": page, "expand": "tags"},
            headers=headers, timeout=20,
        )
        data = r.json()
        items = data.get("items", [])
        for b in items:
            if b.get("alias") == alias:
                return b
        if len(items) < 50:
            break
        page += 1
        time.sleep(0.2)
    return None


def find_local_mp3(stem: str) -> Path | None:
    """Try several name variants to find the local MP3."""
    candidates = [
        BEATS_DIR / f"{stem}.mp3",
        BEATS_DIR / f"{stem}.wav",
    ]
    # Also try with spaces
    space_name = stem.replace("_", " ")
    candidates += [
        BEATS_DIR / f"{space_name}.mp3",
        BEATS_DIR / f"{space_name}.wav",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fuzzy: find any file whose stem matches
    for f in BEATS_DIR.glob("*.mp3"):
        if safe_stem(f.stem) == stem:
            return f
    for f in BEATS_DIR.glob("*.wav"):
        if safe_stem(f.stem) == stem:
            return f
    return None


def do_airbit_login(page, pw_timeout):
    """Log into Airbit. Returns True on success."""
    from playwright.sync_api import TimeoutError as PWTimeout

    page.goto("https://accounts.airbit.com/", wait_until="networkidle", timeout=60000)
    time.sleep(2)
    try:
        page.wait_for_selector('input[name="username"], input[name="email"]', timeout=20000)
    except PWTimeout:
        page.goto("https://airbit.com/login", wait_until="networkidle", timeout=60000)
        time.sleep(3)
        page.wait_for_selector('input[name="username"], input[name="email"]', timeout=20000)

    page.fill('input[name="username"]', AIRBIT_EMAIL)
    time.sleep(0.4)
    page.fill('input[name="password"]', AIRBIT_PASSWORD)
    time.sleep(0.4)
    page.click('button[type="submit"]')

    try:
        page.wait_for_url(lambda url: "accounts.airbit.com" not in url, timeout=30000)
    except PWTimeout:
        time.sleep(5)

    if "accounts.airbit.com" in page.url:
        print("  ❌ Login failed — check credentials in .env")
        return False

    print("  ✓ Logged in")
    return True


def upload_audio_to_beat(page, beat_id: int, mp3_path: Path) -> bool:
    """Navigate to beat edit page and upload the audio file."""
    from playwright.sync_api import TimeoutError as PWTimeout

    edit_url = f"https://app.airbit.com/beats/{beat_id}/edit"
    page.goto(edit_url, wait_until="networkidle", timeout=60000)
    time.sleep(2)

    # Dismiss cookie overlays
    page.evaluate("""() => {
        document.querySelectorAll('body > div').forEach(el => {
            if (window.getComputedStyle(el).position === 'fixed') el.remove();
        });
    }""")
    time.sleep(0.3)

    # Click "Files" tab
    page.evaluate("""() => {
        const tab = document.querySelector('a[href="#files-and-trackout-tab"]');
        if (tab) tab.click();
    }""")
    time.sleep(1.5)

    # Find tagged MP3 input (name="tagged_mp3" or type=file accepting audio)
    audio_input = None
    for selector in [
        'input[name="tagged_mp3"]',
        'input[name="audio_file"]',
        'input[name="beat_file"]',
        'input[type="file"][accept*="audio"]',
        'input[type="file"][accept*="mp3"]',
        # Generic file inputs in the files tab
        '#files-and-trackout-tab input[type="file"]',
    ]:
        el = page.query_selector(selector)
        if el:
            audio_input = el
            print(f"  Found audio input: {selector}")
            break

    if not audio_input:
        # Dump all file inputs for debugging
        inputs = page.query_selector_all('input[type="file"]')
        print(f"  ⚠ No audio input found. All file inputs on page:")
        for inp in inputs:
            print(f"    name={inp.get_attribute('name')} accept={inp.get_attribute('accept')}")
        return False

    # Upload the file
    audio_input.set_input_files(str(mp3_path))
    time.sleep(2)

    # Click Save
    saved = False
    for btn in page.query_selector_all("button"):
        try:
            if btn.is_visible() and "save" in (btn.inner_text() or "").lower():
                btn.click()
                saved = True
                break
        except Exception:
            pass

    if not saved:
        page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                if (b.textContent.toLowerCase().includes('save') && !b.disabled) {
                    b.click(); break;
                }
            }
        }""")

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(1.5)

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--alias",   help="Fix a single listing by its Airbit alias")
    args = parser.parse_args()

    import requests
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    # Build work list
    if args.alias:
        work_aliases = {args.alias: KNOWN_MISMATCHES.get(args.alias, args.alias)}
    else:
        work_aliases = KNOWN_MISMATCHES

    fixed_log = json.loads(FIXED_LOG.read_text()) if FIXED_LOG.exists() else {}

    print("=" * 60)
    print("  Airbit Audio Mismatch Fixer")
    print("=" * 60)

    # Verify local files exist first
    print("\n[1/3] Checking local MP3 files …")
    work: list[tuple[str, Path, int]] = []  # (alias, mp3_path, beat_id)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": f"{STORE_BASE}/",
        "Origin": STORE_BASE,
    }

    # Fetch all beats once to get IDs
    print("  Fetching beat list from Airbit …")
    beats_by_alias = {}
    page_num = 1
    while True:
        r = requests.get(
            f"{AIRBIT_BASE}/users/{AIRBIT_USER_ID}/beats",
            params={"limit": 50, "page": page_num, "expand": "tags"},
            headers=headers, timeout=20,
        )
        data = r.json()
        items = data.get("items", [])
        for b in items:
            beats_by_alias[b.get("alias", "")] = b
        if len(items) < 50:
            break
        page_num += 1
        time.sleep(0.2)
    print(f"  ✓ {len(beats_by_alias)} beats fetched")

    for alias, stem in work_aliases.items():
        if alias in fixed_log:
            print(f"  [SKIP] {alias} — already fixed")
            continue

        beat = beats_by_alias.get(alias)
        if not beat:
            print(f"  [MISS] {alias} — not found on Airbit")
            continue

        beat_id = beat.get("id")
        mp3 = find_local_mp3(stem)
        if not mp3:
            print(f"  [MISS] {alias} → stem '{stem}' — no local MP3 found")
            continue

        print(f"  [OK  ] {alias} → {mp3.name}  (beat_id: {beat_id})")
        work.append((alias, mp3, beat_id, beat.get("name", "")))

    print(f"\n  Ready to fix: {len(work)}")

    if not work:
        print("Nothing to fix.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would upload:")
        for alias, mp3, beat_id, name in work:
            print(f"  {alias:30s} ← {mp3.name}  (listing: '{name}')")
        return

    # Launch browser
    print(f"\n[2/3] Launching browser …")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx_kwargs = {"viewport": {"width": 1280, "height": 800}}
        if SESSION_F.exists():
            ctx_kwargs["storage_state"] = str(SESSION_F)

        ctx  = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        # Check / restore session
        needs_login = True
        if SESSION_F.exists():
            try:
                page.goto("https://app.airbit.com/", timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
                if "accounts.airbit.com" not in page.url and "/login" not in page.url:
                    print("  Session still valid ✓")
                    needs_login = False
            except Exception:
                pass

        if needs_login:
            print(f"  Logging in as {AIRBIT_EMAIL} …")
            if not do_airbit_login(page, PWTimeout):
                browser.close()
                sys.exit(1)
            ctx.storage_state(path=str(SESSION_F))

        # Fix each mismatch
        print(f"\n[3/3] Re-uploading {len(work)} audio files …")
        ok = fail = 0

        for i, (alias, mp3, beat_id, listing_name) in enumerate(work, 1):
            print(f"\n  [{i}/{len(work)}] {alias}  →  {mp3.name}")
            print(f"    Listing: '{listing_name}'")

            try:
                success = upload_audio_to_beat(page, beat_id, mp3)
                if success:
                    print(f"    ✓ Uploaded successfully")
                    fixed_log[alias] = {
                        "alias":      alias,
                        "stem":       str(mp3.stem),
                        "mp3":        str(mp3.name),
                        "beat_id":    beat_id,
                        "listing":    listing_name,
                        "fixed_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    FIXED_LOG.write_text(json.dumps(fixed_log, indent=2))
                    ok += 1
                else:
                    print(f"    ⚠ Upload step failed — check manually")
                    fail += 1
            except Exception as e:
                print(f"    ❌ Error: {e}")
                fail += 1

        browser.close()

    print(f"\n{'='*60}")
    print(f"  Done — ✅ fixed: {ok}  ❌ failed: {fail}")
    print(f"{'='*60}")
    if ok:
        print(f"  Fixed beats logged to: {FIXED_LOG.name}")


if __name__ == "__main__":
    main()
