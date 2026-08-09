#!/usr/bin/env python3
"""link_audit.py — YouTube ↔ Airbit link integrity audit + sync.

Cross-checks EVERY video on the channel that carries an Airbit link against
the live Airbit store:

  DEAD      — description links a slug that no longer exists on the store
  MISMATCH  — linked slug exists but is a DIFFERENT beat than the video
  MISSING   — beat video has no per-beat link but a matching listing exists
  OK        — link resolves to the right listing

Usage:
  python scripts/link_audit.py           # audit + report only
  python scripts/link_audit.py --fix     # audit, then repair YT descriptions

Fixes are full-snippet videos().update calls (title/categoryId/tags resent)
so tags are never wiped. Ambiguous matches are reported, never auto-fixed.
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import airbit_upload as au
from youtube_auth import get_youtube_service_with_fallback

STORE_BASE = "https://leekthatsfy3.infinity.airbit.com"
LINK_RE = re.compile(r"https://leekthatsfy3\.infinity\.airbit\.com/beats/([A-Za-z0-9!%_-]+)")
AIRBIT_USER_ID = 455547  # LeekThatsFy3 (from the store's public API)


def fetch_store_via_api():
    """Live store listings via Airbit's unauthenticated public API.

    Returns {slug: {"title":..., "url":...}} like scrape_store_beats, but in
    seconds and with no browser. Cursor-paginated. Returns {} on any failure
    so the caller can fall back to the selenium scrape.
    """
    import json as _json
    import urllib.request
    beats, cursor = {}, None
    try:
        while True:
            url = f"https://api.airbit.com/users/{AIRBIT_USER_ID}/beats?limit=100"
            if cursor:
                url += f"&cursor={cursor}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": f"{STORE_BASE}/",
                "Origin": STORE_BASE,
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = _json.loads(resp.read())
            for it in data.get("items", []):
                slug = it.get("alias") or ""
                if slug:
                    beats[slug] = {"title": it.get("name", ""),
                                   "url": f"{STORE_BASE}/beats/{slug}"}
            cursor = data.get("cursor")
            if not cursor or not data.get("items"):
                break
    except Exception as e:
        print(f"[WARN] Airbit API fetch failed ({e}) — will fall back to browser scrape")
        return {}
    return beats


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def names_match(a: str, b: str) -> bool:
    """Fuzzy-compare normalized beat names.

    YouTube titles pass through upload.py's profanity filter (fuk → F**k),
    so the live title can differ from the listing title by censored chars —
    an exact normalized compare would false-positive those as mismatches.
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True  # can't judge — don't flag
    if na == nb or na in nb or nb in na:
        return True
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85


def beat_name_from_video_title(title: str) -> str:
    t = title.replace("#Shorts", "").strip()
    m = re.search(r'[-–]\s*["“](.+?)["”]\s*$', t)
    if m:
        return m.group(1)
    m = re.search(r'["“](.+?)["”]', t)
    return m.group(1) if m else ""


def collect_channel_videos(yt):
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    vids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=pl,
                                    maxResults=50, pageToken=tok).execute()
        for it in r["items"]:
            sn = it["snippet"]
            vids.append({
                "id": it["contentDetails"]["videoId"],
                "title": sn.get("title", ""),
                "desc": sn.get("description", ""),
            })
        tok = r.get("nextPageToken")
        if not tok:
            break
    return vids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help="repair bad links on YouTube (default: report only)")
    args = ap.parse_args()

    # 1) live store state — public API first (seconds, no browser), selenium fallback
    store = fetch_store_via_api()
    if not store:
        store = au.scrape_store_beats()  # {slug: {"title":..., "url":...}}
    if not store:
        print("[FAIL] could not read the Airbit store — aborting audit")
        return 1
    print(f"[+] live store listings: {len(store)}")
    by_name = {}
    for slug, info in store.items():
        by_name.setdefault(norm(info.get("title", "")), []).append(slug)

    # 2) every channel video
    yt = get_youtube_service_with_fallback()
    vids = collect_channel_videos(yt)
    print(f"[+] channel videos scanned: {len(vids)}")

    dead, mismatch, missing, ambiguous, ok = [], [], [], [], []
    for v in vids:
        links = LINK_RE.findall(v["desc"])
        bname = beat_name_from_video_title(v["title"])
        nb = norm(bname)
        if not links:
            # only flag MISSING when we can confidently name the beat and a
            # unique live listing exists for it
            if nb and len(by_name.get(nb, [])) == 1 and "airbit.com" in v["desc"]:
                missing.append((v, by_name[nb][0]))
            continue
        slug = links[0]
        if slug not in store:
            cands = by_name.get(nb, [])
            if len(cands) == 1:
                dead.append((v, slug, cands[0]))
            else:
                ambiguous.append((v, slug, cands))
            continue
        listing_title = store[slug].get("title", "")
        if not names_match(bname, listing_title):
            cands = by_name.get(nb, [])
            mismatch.append((v, slug, listing_title, cands[0] if len(cands) == 1 else None))
        else:
            ok.append(v)

    print(f"\n=== AUDIT RESULT ===")
    print(f"  OK:        {len(ok)}")
    print(f"  DEAD:      {len(dead)}")
    print(f"  MISMATCH:  {len(mismatch)}")
    print(f"  MISSING:   {len(missing)}")
    print(f"  AMBIGUOUS: {len(ambiguous)}")

    for v, slug, fix_to in dead:
        print(f"  [DEAD]     {v['id']} '{v['title'][:50]}' → /beats/{slug} (fix → /beats/{fix_to})")
    for v, slug, lt, fix_to in mismatch:
        print(f"  [MISMATCH] {v['id']} '{v['title'][:50]}' links '{lt}' at /beats/{slug}"
              + (f" (fix → /beats/{fix_to})" if fix_to else " (no unique fix)"))
    for v, slug in missing:
        print(f"  [MISSING]  {v['id']} '{v['title'][:50]}' (add /beats/{slug})")
    for v, slug, cands in ambiguous:
        print(f"  [AMBIG]    {v['id']} '{v['title'][:50]}' → /beats/{slug}; candidates: {cands}")

    if not args.fix:
        if dead or mismatch or missing:
            print("\nRun with --fix to repair.")
        return 0 if not (dead or mismatch) else 1

    # 3) repair
    to_fix = [(v, f"{STORE_BASE}/beats/{fix_to}") for v, slug, fix_to in dead] \
        + [(v, f"{STORE_BASE}/beats/{fix_to}") for v, slug, lt, fix_to in mismatch if fix_to] \
        + [(v, f"{STORE_BASE}/beats/{slug}") for v, slug in missing]
    fixed = 0
    for v, new_url in to_fix:
        r = yt.videos().list(part="snippet", id=v["id"]).execute()
        if not r.get("items"):
            continue
        sn = r["items"][0]["snippet"]
        desc = sn.get("description", "")
        if LINK_RE.search(desc):
            new_desc = LINK_RE.sub(new_url, desc, count=1)
        else:
            new_desc = desc.replace(f"{STORE_BASE}/beats", new_url, 1)
        if new_desc == desc:
            continue
        yt.videos().update(part="snippet", body={"id": v["id"], "snippet": {
            "title": sn["title"], "categoryId": sn.get("categoryId", "10"),
            "description": new_desc, "tags": sn.get("tags", []),
        }}).execute()
        fixed += 1
        print(f"  [FIXED] {v['id']} → {new_url}")
        time.sleep(0.5)
    print(f"\n[COMPLETE] {fixed} video description(s) repaired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
