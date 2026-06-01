#!/usr/bin/env python3
"""
sync_airbit_artwork.py
----------------------
Auto-pilot script that logs into your Airbit dashboard via headless browser,
then uploads each beat's thumbnail (output/{stem}_thumb.jpg) as the cover art.

Requirements:
  1. Add to .env:
       AIRBIT_EMAIL=your@email.com
       AIRBIT_PASSWORD=yourpassword
  2. pip install playwright && python -m playwright install chromium

Usage:
    python sync_airbit_artwork.py              # sync all beats missing artwork
    python sync_airbit_artwork.py --force      # re-upload even existing artwork
    python sync_airbit_artwork.py --only "hood_legend,army"
    python sync_airbit_artwork.py --dry-run    # show what would be uploaded

How it works:
    1. Logs into airbit.com with your credentials
    2. Fetches beat list from Airbit API (same as sync_airbit_links.py)
    3. For each beat that has a local thumbnail (output/{stem}_thumb.jpg):
       - Navigates to the beat edit page
       - Uploads the thumbnail as artwork
       - Saves

The session cookie is saved to airbit_session.json so you only log in once.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_DIR   = Path(__file__).resolve().parent
OUTPUT_DIR    = PROJECT_DIR / "output"
THUMBS_DIR    = PROJECT_DIR / "output" / "thumbs"
META_DIR      = PROJECT_DIR / "metadata"
SESSION_FILE  = PROJECT_DIR / "airbit_session.json"
AIRBIT_BASE   = "https://airbit.com"
AIRBIT_API    = "https://api.airbit.com"
AIRBIT_USER_ID = 455547
PAGE_SIZE     = 50

DRY_RUN  = "--dry-run" in sys.argv
FORCE    = "--force"   in sys.argv
ONLY     = None
for i, arg in enumerate(sys.argv):
    if arg == "--only" and i + 1 < len(sys.argv):
        ONLY = {s.strip() for s in sys.argv[i + 1].split(",")}

# ── Load credentials ──────────────────────────────────────────────────────────

def load_env():
    env_path = PROJECT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_env()
AIRBIT_EMAIL    = os.environ.get("AIRBIT_EMAIL", "")
AIRBIT_PASSWORD = os.environ.get("AIRBIT_PASSWORD", "")


# ── Stem helper ───────────────────────────────────────────────────────────────

def safe_stem(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s


# ── Airbit API — fetch beat list ──────────────────────────────────────────────

def fetch_airbit_beats() -> list[dict]:
    import urllib.request
    beats = []
    page  = 1
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept":     "application/json",
        "Referer":    "https://leekthatsfy3.infinity.airbit.com/",
        "Origin":     "https://leekthatsfy3.infinity.airbit.com",
    }
    while True:
        url = (
            f"{AIRBIT_API}/users/{AIRBIT_USER_ID}/beats"
            f"?limit={PAGE_SIZE}&page={page}&expand=tags"
        )
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data  = json.loads(resp.read())
        items = data.get("items", [])
        beats.extend(items)
        print(f"  API page {page}: {len(items)} beats (total: {len(beats)})")
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)
    return beats


# ── Build stem → beat_id map ──────────────────────────────────────────────────

def build_id_map(beats: list[dict]) -> dict[str, dict]:
    """Return {stem -> beat_dict} with both full-name and short-name stems."""
    m = {}
    for b in beats:
        full_stem = safe_stem(b["name"])
        m[full_stem] = b
        # Strip "Artist Type Beat - " prefix
        short_name = re.sub(
            r'^.*?type beat\s*-\s*"?', "", b["name"], flags=re.IGNORECASE
        ).strip('" ')
        if short_name and short_name.lower() != b["name"].lower():
            short_stem = safe_stem(short_name)
            if short_stem and short_stem not in m:
                m[short_stem] = b
    return m


# ── Playwright automation ─────────────────────────────────────────────────────

def run_sync():
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    if not AIRBIT_EMAIL or not AIRBIT_PASSWORD or \
       "YOUR_AIRBIT" in AIRBIT_EMAIL or "YOUR_AIRBIT" in AIRBIT_PASSWORD:
        print("❌  Airbit credentials not set.")
        print("    Add to .env:")
        print("      AIRBIT_EMAIL=your@email.com")
        print("      AIRBIT_PASSWORD=yourpassword")
        sys.exit(1)

    print("=" * 60)
    print("  Airbit Auto Cover Art Sync")
    print("=" * 60)

    # Fetch beat list
    print("\n[1/4] Fetching beats from Airbit API …")
    airbit_beats = fetch_airbit_beats()
    id_map = build_id_map(airbit_beats)
    print(f"  ✓  {len(airbit_beats)} beats on Airbit, {len(id_map)} stems mapped")

    # Build work list: local stems that have a thumbnail + match an Airbit beat
    print("\n[2/4] Finding stems with thumbnails to upload …")
    work: list[tuple[str, Path, dict]] = []  # (stem, thumb_path, airbit_beat)

    # Collect all stems that have any thumbnail
    all_stems: set[str] = set()
    for search_dir in [OUTPUT_DIR, THUMBS_DIR]:
        for p in search_dir.glob("*_art.jpg"):
            all_stems.add(p.stem.replace("_art", ""))
        for p in search_dir.glob("*_thumb.jpg"):
            all_stems.add(p.stem.replace("_thumb", ""))

    for stem in sorted(all_stems):
        if ONLY and stem not in ONLY:
            continue
        beat = id_map.get(stem)
        if not beat:
            continue  # no matching Airbit listing
        # Priority: output/thumbs/{stem}_thumb.jpg > output/{stem}_thumb.jpg > _art.jpg
        candidates = [
            THUMBS_DIR / f"{stem}_thumb.jpg",
            OUTPUT_DIR / f"{stem}_thumb.jpg",
            OUTPUT_DIR / f"{stem}_art.jpg",
            THUMBS_DIR / f"{stem}_art.jpg",
        ]
        best = next((p for p in candidates if p.exists()), None)
        if not best:
            continue
        work.append((stem, best, beat))

    if not work:
        print("  Nothing to upload — no matched thumbnails found.")
        return

    print(f"  ✓  {len(work)} thumbnails to upload")
    for stem, thumb, beat in work:
        print(f"     {stem:45s} → {beat['name'][:40]}")

    if DRY_RUN:
        print("\n[DRY RUN] No uploads performed.")
        return

    # Launch browser
    print(f"\n[3/4] Launching browser and logging in …")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # Restore session if we have one
        ctx_kwargs = {"viewport": {"width": 1280, "height": 800}}
        if SESSION_FILE.exists():
            print("  Restoring saved session …")
            ctx_kwargs["storage_state"] = str(SESSION_FILE)

        ctx  = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        # Check if session is still valid
        needs_login = True
        if SESSION_FILE.exists():
            try:
                page.goto(f"{AIRBIT_BASE}/dashboard", timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
                # If redirected to accounts.airbit.com we need to re-login
                if "accounts.airbit.com" not in page.url and "/login" not in page.url and "/signin" not in page.url:
                    print("  Session still valid ✓")
                    needs_login = False
            except Exception:
                pass

        if needs_login:
            print(f"  Logging in as {AIRBIT_EMAIL} …")
            # Airbit login is a JS SPA — the form lives at the ROOT of accounts.airbit.com
            # (NOT /login which returns 405 on GET).
            # POST target is /login but we navigate to / to get the rendered form.
            page.goto("https://accounts.airbit.com/", wait_until="networkidle", timeout=60000)
            time.sleep(2)

            # The form fields use name="username" and name="password" per ab.loginEmailFieldName
            try:
                page.wait_for_selector('input[name="username"], input[name="email"]', timeout=20000)
            except PWTimeout:
                print("  ⚠️  Login form not found, trying airbit.com/login redirect …")
                page.goto(f"{AIRBIT_BASE}/login", wait_until="networkidle", timeout=60000)
                time.sleep(3)
                page.wait_for_selector('input[name="username"], input[name="email"]', timeout=20000)

            # Fill username (email)
            page.fill('input[name="username"]', AIRBIT_EMAIL)
            time.sleep(0.5)

            # Fill password
            page.fill('input[name="password"]', AIRBIT_PASSWORD)
            time.sleep(0.5)

            # Submit — button[type="submit"] inside the login form
            page.click('button[type="submit"]')
            # Wait for navigation away from accounts.airbit.com
            try:
                page.wait_for_url(lambda url: "accounts.airbit.com" not in url, timeout=30000)
            except PWTimeout:
                # May redirect back to dashboard directly on accounts domain
                time.sleep(5)

            if "accounts.airbit.com" in page.url and (
                "/login" in page.url or page.url.rstrip("/") == "https://accounts.airbit.com"
            ):
                # Still on login page — check for error message
                err_el = page.query_selector(".alert, .error, [class*=error], [class*=alert]")
                err_msg = err_el.inner_text() if err_el else "unknown"
                print(f"❌  Login failed: {err_msg}")
                print("    Check AIRBIT_EMAIL / AIRBIT_PASSWORD in .env")
                browser.close()
                sys.exit(1)

            print("  Logged in ✓")
            # Save session
            ctx.storage_state(path=str(SESSION_FILE))
            print(f"  Session saved to {SESSION_FILE.name}")

        # Upload thumbnails
        print(f"\n[4/4] Uploading {len(work)} thumbnails …")
        ok_count   = 0
        fail_count = 0

        # Dismiss cookie banner once — it reappears on each page load but
        # we can nuke it via JS before each interaction
        def dismiss_cookie_overlay():
            page.evaluate("""() => {
                document.querySelectorAll('body > div').forEach(el => {
                    if (window.getComputedStyle(el).position === 'fixed') el.remove();
                });
            }""")

        for i, (stem, thumb_path, beat) in enumerate(work, 1):
            beat_id = beat.get("id") or beat.get("beat_id") or beat.get("listing_id")
            name    = beat["name"]
            print(f"  [{i}/{len(work)}] {stem} → {name[:40]} (id: {beat_id})")

            try:
                # Navigate to beat edit page on app.airbit.com (NOT airbit.com/dashboard)
                edit_url = f"https://app.airbit.com/beats/{beat_id}/edit"
                page.goto(edit_url, wait_until="networkidle", timeout=60000)
                time.sleep(2)

                # Remove cookie consent overlay (fixed-position divs at body root)
                dismiss_cookie_overlay()
                time.sleep(0.3)

                # Click the "Files" tab via JS to reveal the artwork input
                page.evaluate("""() => {
                    const tab = document.querySelector('a[href="#files-and-trackout-tab"]');
                    if (tab) tab.click();
                }""")
                time.sleep(1.5)

                # Find artwork file input (name="artwork_file")
                artwork_input = page.query_selector('input[name="artwork_file"]')
                if not artwork_input:
                    print(f"     ⚠️  No artwork input found — skipping")
                    fail_count += 1
                    continue

                # Upload the thumbnail
                artwork_input.set_input_files(str(thumb_path))
                time.sleep(1.5)

                # Click the visible green Save button
                saved = False
                for btn in page.query_selector_all("button"):
                    try:
                        if btn.is_visible() and "save" in btn.inner_text().lower():
                            btn.click()
                            saved = True
                            break
                    except Exception:
                        pass

                if not saved:
                    # Fallback: JS click on any save button
                    page.evaluate("""() => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            if (b.textContent.toLowerCase().includes('save') && !b.disabled) {
                                b.click(); break;
                            }
                        }
                    }""")

                # Wait for form submission (302 redirect back to edit page)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                time.sleep(1)

                print(f"     ✓  Uploaded {thumb_path.name}")
                ok_count += 1

                # Save session periodically
                if i % 10 == 0:
                    ctx.storage_state(path=str(SESSION_FILE))

            except Exception as e:
                print(f"     ✗  {stem}: {e}")
                fail_count += 1
                # Save session on errors too
                try:
                    ctx.storage_state(path=str(SESSION_FILE))
                except Exception:
                    pass

        # Final session save
        try:
            ctx.storage_state(path=str(SESSION_FILE))
        except Exception:
            pass

        browser.close()

    print(f"\n{'='*60}")
    print(f"  Done!  ✓ {ok_count} uploaded  ✗ {fail_count} failed")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_sync()
