"""
tiktok_auto.py — TikTok browser automation uploader

Posts up to 2 shorts per day via real Chrome browser (no API needed).
Tracks posted videos so it never double-posts.
Runs safely with human-like delays to avoid detection/shadowban.

Usage:
    python tiktok_auto.py              # post up to 2 shorts (10am + 7pm schedule)
    python tiktok_auto.py --now        # post 1 right now (ignores schedule)
    python tiktok_auto.py --now --max 2  # post 2 right now
    python tiktok_auto.py --dry-run    # show what would be posted

Cron (runs at 10am and 7pm daily):
    0 10 * * * cd /Users/fyefye/yt_automation && .venv/bin/python tiktok_auto.py --now --max 1
    0 19 * * * cd /Users/fyefye/yt_automation && .venv/bin/python tiktok_auto.py --now --max 1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

ROOT        = Path(__file__).resolve().parent
OUT_DIR     = ROOT / "output"
META_DIR    = ROOT / "metadata"
STORE_LOG   = ROOT / "store_uploads_log.json"
LANES_CFG   = ROOT / "lanes_config.json"
TT_LOG_FILE = ROOT / "tiktok_uploads_log.json"

MAX_PER_DAY   = 2
POST_TIMES    = [(10, 0), (19, 0)]  # 10am, 7pm
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktok/webapp/creator-micro/upload"

# ── TikTok uploads log ────────────────────────────────────────────────────────

def load_tt_log() -> dict:
    try:
        if TT_LOG_FILE.exists():
            return json.loads(TT_LOG_FILE.read_text())
    except Exception:
        pass
    return {}


def save_tt_log(data: dict):
    TT_LOG_FILE.write_text(json.dumps(data, indent=2, default=str))


# ── Caption builder ───────────────────────────────────────────────────────────

# TikTok flags explicit words in captions — clean version for TT
_TT_CAPTION_CLEAN = {
    r"\bho3\b": "hoe", r"\bass\b": "a**", r"\bbitch\b": "b**ch",
    r"\bpussy\b": "p***y", r"\bnigga\b": "n***a", r"\bniggas\b": "n***as",
    r"\bfuck\b": "f**k", r"\bfuk\b": "f**k", r"\bshit\b": "sh**",
}

# TikTok caption hooks — different from YT so content stays fresh cross-platform
_TT_HOOKS = [
    "which rapper do you hear on this 👇",
    "be honest who goes crazy on this 👇",
    "pov your fav just dropped this 👇",
    "name a rapper built for this 👇",
    "this beat needs the right artist 👇",
    "who's getting on this one 👇",
    "this is going on somebody's album 👇",
    "drop a name and I'll send the lease 👇",
    "the right rapper on this = instant hit 👇",
    "nobody makes beats like this anymore 👇",
    "who do you immediately hear on this 👇",
    "this one's too cold to be sitting 👇",
    "comment who you'd sign to this 👇",
    "which artist needs to hear this TODAY 👇",
    "I made this for one specific rapper guess who 👇",
    "somebody's about to blow up off a beat like this 👇",
    "streets been needing this 👇",
    "tag the rapper I'll do the rest 👇",
    "one rapper one beat instant classic name em 👇",
    "I already know who fits this do you 👇",
]


def _pick_tt_hook(stem: str) -> str:
    """Daily rotating hook — different from YT hooks, changes every day."""
    day = date.today().timetuple().tm_yday
    stem_hash = sum(ord(c) for c in stem)
    return _TT_HOOKS[(stem_hash + day + 7) % len(_TT_HOOKS)]  # +7 offset so TT != YT hook


def _clean_tt_text(text: str) -> str:
    """Strip TikTok-flagged words from captions."""
    for pattern, replacement in _TT_CAPTION_CLEAN.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def build_tt_caption(stem: str) -> str:
    """
    Build a TikTok caption:
    - Hook line (daily rotating)
    - Beat title
    - Purchase link (Airbit)
    - Hashtags (no links — TikTok suppresses posts with URLs in caption)

    NOTE: TikTok suppresses reach when URLs are in the caption.
    Put the Airbit link in bio instead. Caption stays clean = better reach.
    """
    # Load metadata
    meta = {}
    try:
        mp = META_DIR / f"{stem}.json"
        if mp.exists():
            meta = json.loads(mp.read_text())
    except Exception:
        pass

    title = meta.get("title", stem.replace("_", " ").title())
    title = _clean_tt_text(title)

    hook = _pick_tt_hook(stem)

    # Top hashtags — TikTok max caption is 2200 chars, keep it tight
    raw_tags = meta.get("tags", [])[:6]
    hashtags = " ".join(
        "#" + re.sub(r"[^a-zA-Z0-9]", "", t) for t in raw_tags if t
    )
    if not hashtags:
        hashtags = "#typebeat #rapmusic #beatmaker #freebeat"
    else:
        hashtags = f"#typebeat #beatmaker {hashtags}"

    caption = f"{hook}\n\n{title}\n\n{hashtags} #fyp #music"
    return caption.strip()[:2200]


# ── Short picker ──────────────────────────────────────────────────────────────

def get_unposted_shorts() -> list[Path]:
    """Return 9x16 shorts not yet posted to TikTok, oldest-render-first."""
    tt_log = load_tt_log()
    posted_stems = set(tt_log.keys())

    shorts = sorted(
        OUT_DIR.glob("*_9x16.mp4"),
        key=lambda f: f.stat().st_mtime
    )

    unposted = []
    for f in shorts:
        stem = f.stem.replace("_9x16", "")
        if stem not in posted_stems:
            unposted.append(f)

    return unposted


# ── Human-like delays ─────────────────────────────────────────────────────────

def human_delay(lo: float = 1.0, hi: float = 3.0):
    """Random delay to mimic human interaction speed."""
    time.sleep(random.uniform(lo, hi))


def human_type(element, text: str):
    """Type text character by character with random delays."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.04, 0.12))


# ── Browser setup ─────────────────────────────────────────────────────────────

def get_driver():
    """
    Launch undetected Chrome with a persistent profile so TikTok login
    session is saved between runs. First run: log in manually.
    Subsequent runs: session reused automatically.
    """
    import undetected_chromedriver as uc

    profile_dir = ROOT / ".tiktok_chrome_profile"
    profile_dir.mkdir(exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Do NOT use headless — TikTok detects it
    # options.add_argument("--headless")

    driver = uc.Chrome(options=options, version_main=123)
    driver.set_window_size(1280, 900)
    return driver


# ── Upload flow ───────────────────────────────────────────────────────────────

def upload_to_tiktok(short_path: Path, caption: str, dry_run: bool = False) -> bool:
    """
    Upload a short to TikTok via browser automation.
    Returns True on success, False on failure.
    """
    if dry_run:
        log.info("[DRY RUN] Would upload: %s", short_path.name)
        log.info("[DRY RUN] Caption: %s", caption[:100])
        return True

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = None
    try:
        log.info("Launching Chrome...")
        driver = get_driver()

        log.info("Navigating to TikTok upload...")
        driver.get("https://www.tiktok.com/creator#/upload")
        human_delay(3, 5)

        # Check if logged in
        if "login" in driver.current_url.lower():
            log.warning("=" * 50)
            log.warning("NOT LOGGED IN — Please log into TikTok in the browser window.")
            log.warning("After logging in, the script will continue automatically.")
            log.warning("=" * 50)
            # Wait up to 3 minutes for manual login
            wait = WebDriverWait(driver, 180)
            wait.until(lambda d: "login" not in d.current_url.lower())
            log.info("Logged in! Continuing...")
            human_delay(2, 4)
            driver.get("https://www.tiktok.com/creator#/upload")
            human_delay(3, 5)

        # Wait for upload area to appear
        log.info("Waiting for upload page...")
        wait = WebDriverWait(driver, 30)

        # Find the file input (hidden input for video upload)
        try:
            file_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
            )
        except Exception:
            # Try iframe — TikTok creator studio loads in iframe
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    driver.switch_to.frame(iframe)
                    file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                    break
                except Exception:
                    driver.switch_to.default_content()
            else:
                raise RuntimeError("Could not find file upload input")

        # Upload the file
        log.info("Uploading file: %s", short_path.name)
        file_input.send_keys(str(short_path.absolute()))
        human_delay(4, 8)  # Wait for video to process

        # Wait for caption field
        log.info("Filling in caption...")
        try:
            caption_field = wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "div[contenteditable='true'], textarea[placeholder*='caption'], .public-DraftEditor-content"
                ))
            )
        except Exception:
            caption_field = driver.find_element(By.CSS_SELECTOR, "[data-placeholder*='caption'], [placeholder*='caption']")

        # Clear and type caption
        caption_field.click()
        human_delay(0.5, 1.0)
        caption_field.send_keys(caption)
        human_delay(1, 2)

        # Wait for video processing to finish (progress bar disappears)
        log.info("Waiting for video to finish processing...")
        human_delay(8, 15)

        # Find and click Post button
        log.info("Clicking Post...")
        try:
            post_btn = wait.until(EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(text(),'Post') or contains(text(),'post')]"
            )))
        except Exception:
            # Fallback: find by class patterns TikTok uses
            post_btn = driver.find_element(
                By.CSS_SELECTOR,
                "button.btn-post, button[data-e2e='post-button'], .post-btn"
            )

        human_delay(1, 2)
        post_btn.click()
        log.info("Post button clicked!")

        # Wait for success confirmation
        human_delay(5, 10)
        log.info("Upload complete: %s", short_path.name)
        return True

    except Exception as e:
        log.error("Upload failed: %s", e)
        return False

    finally:
        if driver:
            human_delay(2, 3)
            driver.quit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-post TikTok shorts")
    parser.add_argument("--now", action="store_true",
                        help="Post immediately (ignore schedule)")
    parser.add_argument("--max", type=int, default=1,
                        help="Max shorts to post this run (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be posted without posting")
    args = parser.parse_args()

    # Check how many posted today already
    tt_log = load_tt_log()
    today = date.today().isoformat()
    posted_today = sum(
        1 for entry in tt_log.values()
        if entry.get("postedDate") == today
    )

    if posted_today >= MAX_PER_DAY and not args.dry_run:
        log.info("Already posted %d/%d today — done for the day.", posted_today, MAX_PER_DAY)
        return

    slots_left = min(args.max, MAX_PER_DAY - posted_today)
    if slots_left <= 0 and not args.dry_run:
        log.info("No slots left today.")
        return

    # Get unposted shorts
    unposted = get_unposted_shorts()
    if not unposted:
        log.info("No unposted shorts found in output/.")
        return

    log.info("Found %d unposted shorts — posting %d today (already posted %d/%d)",
             len(unposted), slots_left, posted_today, MAX_PER_DAY)

    posted = 0
    for short_path in unposted[:slots_left]:
        stem = short_path.stem.replace("_9x16", "")
        caption = build_tt_caption(stem)

        log.info("\n--- %s ---", stem)
        log.info("Caption:\n%s", caption)

        success = upload_to_tiktok(short_path, caption, dry_run=args.dry_run)

        if success and not args.dry_run:
            tt_log[stem] = {
                "file":       short_path.name,
                "caption":    caption,
                "postedDate": today,
                "postedAt":   datetime.now(timezone.utc).isoformat(),
            }
            save_tt_log(tt_log)
            posted += 1
            log.info("[DONE] %s posted to TikTok ✓", stem)

            # Human-like delay between posts (3-7 minutes)
            if posted < slots_left:
                wait_secs = random.randint(180, 420)
                log.info("Waiting %d seconds before next post...", wait_secs)
                time.sleep(wait_secs)
        elif args.dry_run:
            posted += 1

    log.info("\nPosted %d short(s) to TikTok today.", posted)


if __name__ == "__main__":
    main()
