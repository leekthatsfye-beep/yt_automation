"""
seo_metadata.py

Generates SEO-optimized metadata JSON files in metadata/ for each audio beat
found in beats/.

By default: skips beats that already have a metadata file.
Use --force to regenerate ALL metadata files including existing ones.

Uses lanes_config.json for artist lanes, title/description/tag templates,
and dual-artist combo support.

Uses the same filename normalization rules as render.py (safe_stem).
Does not import from or modify render.py.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parent
BEATS_DIR = ROOT / "beats"
META_DIR  = ROOT / "metadata"
STORE_LOG = ROOT / "store_uploads_log.json"

# ── Load lanes config ────────────────────────────────────────────────────

_LANES_CONFIG_PATH = ROOT / "lanes_config.json"


def _load_lanes_config() -> dict:
    """Load lanes_config.json. Returns empty dict on failure."""
    try:
        if _LANES_CONFIG_PATH.exists():
            return json.loads(_LANES_CONFIG_PATH.read_text())
    except Exception:
        pass
    return {}


_lanes_cfg = _load_lanes_config()

PRODUCER = _lanes_cfg.get("producer_display", "LeekThatsFye")
YEAR     = _lanes_cfg.get("year", 2026)
BEAT_STORE_LINK = _lanes_cfg.get("beat_store_link", "[Link in bio]")
CONTACT  = _lanes_cfg.get("contact", "@leekthatsfy3")

# ── Artist pools by BPM-vibe (mirrors telegram_bot.py) ─────────────────────

_BPM_VIBE = {
    (0,   79):  "emotional",
    (80,  109): "melodic",
    (110, 129): "trap",
    (130, 149): "hard",
    (150, 169): "dark",
    (170, 999): "drill",
}

_TAG_ARTISTS_BY_VIBE = {
    "emotional": [
        "Rod Wave", "Polo G", "Lil Durk", "NBA YoungBoy", "NoCap",
        "Lil Tjay", "Morray", "Toosii", "YNW Melly", "Lil Poppa",
        "Kevin Gates", "Lil Baby", "EST Gee", "Big Sean", "J Cole",
    ],
    "melodic": [
        "Drake", "Gunna", "Future", "A Boogie wit da Hoodie", "Lil Tjay",
        "Don Toliver", "The Weeknd", "6LACK", "Bryson Tiller", "Summer Walker",
        "Giveon", "Brent Faiyaz", "SZA", "Khalid", "Daniel Caesar",
    ],
    "trap": [
        "Travis Scott", "Young Thug", "Lil Uzi Vert", "Playboi Carti", "Metro Boomin",
        "Gunna", "Lil Baby", "Future", "21 Savage", "Offset",
        "Quavo", "Kodak Black", "Lil Keed", "Lil Gotit", "Lil Durk",
    ],
    "hard": [
        "21 Savage", "Moneybagg Yo", "42 Dugg", "Kodak Black", "Lil Baby",
        "Lil Durk", "EST Gee", "Mozzy", "Boosie Badazz", "Kevin Gates",
        "Dave East", "G Herbo", "Fredo Bang", "Rylo Rodriguez", "Lil Reese",
    ],
    "dark": [
        "Rod Wave", "NBA YoungBoy", "Lil Durk", "EST Gee", "Polo G",
        "Kevin Gates", "Mozzy", "Rylo Rodriguez", "Lil Poppa", "NoCap",
        "G Herbo", "Fredo Bang", "Quando Rondo", "Lil Reese", "Lil Baby",
    ],
    "drill": [
        "Pop Smoke", "Fivio Foreign", "Sheff G", "Lil Tjay", "Kay Flock",
        "Bizzy Banks", "Coi Leray", "Central Cee", "Digga D", "Unknown T",
        "Dave", "Headie One", "Loski", "Tion Wayne", "M Huncho",
    ],
}

_BASE_TAGS = [
    "type beat", "free type beat", "rap instrumental",
    "trap beat", "trap instrumental", "free beat",
    f"{YEAR} type beat", "free rap beat", "hip hop instrumental",
    f"new type beat {YEAR}", "beats for sale", PRODUCER.lower(),
    "leek thats fye", f"prod by {PRODUCER.lower()}", f"rap beat {YEAR}",
]

_MOOD_LABELS = {
    "emotional": "emotional melodic",
    "melodic":   "melodic R&B",
    "trap":      "hard trap",
    "hard":      "street hard",
    "dark":      "dark melodic",
    "drill":     "UK drill",
}


def safe_stem(p: Path) -> str:
    """Identical to safe_stem() in render.py."""
    s = p.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def _vibe_from_bpm(bpm: int | None) -> str:
    if not bpm:
        return "trap"
    for (lo, hi), v in _BPM_VIBE.items():
        if lo <= bpm <= hi:
            return v
    return "trap"


def _load_artists_config() -> dict:
    cfg_path = ROOT / "artists_config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception:
            pass
    return {}


_ARTIST_SEO_PROFILES_PATH = ROOT / "artist_seo_profiles.json"


def _load_artist_seo_profiles() -> dict:
    """Load all SEO profiles from artist_seo_profiles.json."""
    try:
        if _ARTIST_SEO_PROFILES_PATH.exists():
            return json.loads(_ARTIST_SEO_PROFILES_PATH.read_text())
    except Exception:
        pass
    return {}


def _load_artist_seo_profile(artist: str) -> dict | None:
    """Load the SEO profile for a specific artist from artist_seo_profiles.json."""
    profiles = _load_artist_seo_profiles()
    return profiles.get(artist)


def _get_artists(vibe: str) -> list[str]:
    pool = list(_TAG_ARTISTS_BY_VIBE.get(vibe, _TAG_ARTISTS_BY_VIBE["trap"]))
    cfg  = _load_artists_config()
    for a in cfg.get("vibes", {}).get(vibe, []):
        if a not in pool:
            pool.insert(0, a)
    return pool


# ── Dual combo helpers ───────────────────────────────────────────────────

def _get_dual_combos() -> list[list[str]]:
    """Get dual artist combos from lanes_config.json."""
    return _lanes_cfg.get("dual_combos", [])


def _find_dual_partner(primary_artist: str) -> str | None:
    """Find a valid dual combo partner for the given artist.
    Returns a random partner from available combos, or None."""
    combos = _get_dual_combos()
    partners = []
    for combo in combos:
        if primary_artist in combo:
            partner = combo[0] if combo[1] == primary_artist else combo[1]
            partners.append(partner)
    if partners:
        return random.choice(partners)
    return None


# ── Title builders ───────────────────────────────────────────────────────

def _build_title_single(artist: str, beat_name: str) -> str:
    """Build title for a single-artist beat using lanes_config template."""
    templates = _lanes_cfg.get("title_template", {})
    template = templates.get("single", '[FREE] {artist} Type Beat - "{beat_name}"')
    return template.format(artist=artist, beat_name=beat_name)


def _build_title_dual(artist1: str, artist2: str, beat_name: str) -> str:
    """Build title for a dual-artist beat using lanes_config template."""
    templates = _lanes_cfg.get("title_template", {})
    template = templates.get("dual", '[FREE] {artist1} x {artist2} Type Beat - "{beat_name}"')
    return template.format(artist1=artist1, artist2=artist2, beat_name=beat_name)


# ── Tag builder ──────────────────────────────────────────────────────────

def build_tags(stem: str, meta: dict) -> list[str]:
    """Build 15-20 clean, relevant tags. No beat name tags, no generic filler."""
    primary_artist = meta.get("seo_artist", "")
    dual_artist = meta.get("seo_artist2", "")

    # Check for artist-specific SEO profile
    profile = _load_artist_seo_profile(primary_artist) if primary_artist else None

    # ── Use lanes_config tag templates if available ──
    tag_templates = _lanes_cfg.get("tag_template", {})

    if profile:
        # Use ONLY artist-curated related artists — no generic vibe pool
        related = profile.get("related_artists", [])
        artists = [primary_artist] + [a for a in related if a != primary_artist]
        artist_base_tags = list(profile.get("base_tags", []))
    else:
        bpm = meta.get("bpm")
        vibe = _vibe_from_bpm(int(bpm) if bpm else None)
        key = meta.get("key", "")
        if "Minor" in key and vibe in ("melodic", "trap"):
            vibe = "dark"
        artists = _get_artists(vibe)
        if primary_artist:
            artists = [primary_artist] + [a for a in artists if a != primary_artist]
        artist_base_tags = []

    # Build candidate tag list — artist base tags first
    candidate_tags = list(artist_base_tags)

    # Primary artist tags from template
    if primary_artist and tag_templates.get("primary_artist_tags"):
        for tmpl in tag_templates["primary_artist_tags"]:
            tag = tmpl.format(artist=primary_artist, year=YEAR)
            if tag.lower() not in {t.lower() for t in candidate_tags}:
                candidate_tags.append(tag)

    # Dual artist tags from template
    if dual_artist and tag_templates.get("dual_artist_tags"):
        for tmpl in tag_templates["dual_artist_tags"]:
            tag = tmpl.format(artist1=primary_artist, artist2=dual_artist, year=YEAR)
            candidate_tags.append(tag)

    # Related artist tags (4-6 related artists, type beat + instrumental)
    for a in artists[1:7]:  # skip [0] which is primary
        candidate_tags.append(f"{a} type beat")
    for a in artists[1:5]:  # top 4 get instrumental variant too
        candidate_tags.append(f"{a} instrumental")

    # Deduplicate, target 15-25 tags, 490 char budget
    seen = set()
    tags = []
    char_budget = 490
    total_chars = 0
    for t in candidate_tags:
        t_clean = t.strip()[:30]
        t_lower = t_clean.lower()
        if t_lower in seen:
            continue
        if total_chars + len(t_clean) + 1 > char_budget or len(tags) >= 25:
            break
        seen.add(t_lower)
        tags.append(t_clean)
        total_chars += len(t_clean) + 1

    return tags


# ── Description builder ──────────────────────────────────────────────────

def _get_purchase_link(stem: str) -> str:
    """Look up the Airbit listing URL for a beat, fall back to store profile."""
    store_profile = _lanes_cfg.get("store_profile_url", "")

    # Try to find a beat-specific store URL
    try:
        if STORE_LOG.exists():
            store_data = json.loads(STORE_LOG.read_text())
            entry = store_data.get(stem, {})
            # Check airbit sub-key first, then top-level url
            airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
            beat_url = airbit_entry.get("url", "")
            if beat_url and beat_url != store_profile:
                # Beat-specific link first, then store profile underneath
                return f"{beat_url}\n\nBrowse all beats:\n{store_profile}" if store_profile else beat_url
    except Exception:
        pass

    # Fall back to store profile URL
    return store_profile or "[Link in bio]"


def build_description(stem: str, meta: dict) -> str:
    """Short, clean description — purchase funnel only, no promotional spam."""
    producer_lower = _lanes_cfg.get("producer", PRODUCER.lower())
    purchase_link = _get_purchase_link(stem)

    # Use lanes_config description template if available
    desc_template = _lanes_cfg.get("description_template")
    if desc_template:
        try:
            desc = desc_template.format(
                producer=producer_lower,
                purchase_link=purchase_link,
            )
            return desc.strip()
        except (KeyError, ValueError):
            pass  # fall through to default

    # Default: clean purchase funnel
    return f"Purchase / Download\n{purchase_link}\n\nprod. {producer_lower}"


# ── Title builder ────────────────────────────────────────────────────────

def _resolve_title(stem: str, meta: dict) -> str:
    """Build YouTube title from lanes_config templates.

    If meta has seo_artist2, uses dual template.
    If meta has seo_artist, uses single template.
    Otherwise returns the plain beat name.
    """
    beat_name = meta.get("beat_name", meta.get("title", stem.replace("_", " ").title()))
    primary = meta.get("seo_artist", "")
    dual = meta.get("seo_artist2", "")

    if primary and dual:
        return _build_title_dual(primary, dual, beat_name)
    elif primary:
        return _build_title_single(primary, beat_name)
    else:
        return beat_name


# ── Main metadata builder ───────────────────────────────────────────────

def build_metadata(stem: str, existing: dict | None = None, lane: str | None = None,
                   artist: str | None = None, dual: bool = False) -> dict:
    """Build complete SEO metadata for a beat.

    Args:
        stem: normalized filename stem
        existing: existing metadata dict to preserve fields from
        lane: lane name (breakfast/lunch/dinner) — auto-assigns artist if provided
        artist: override artist name (takes priority over lane default)
        dual: if True, pick a random dual combo partner for the artist
    """
    meta = dict(existing) if existing else {}

    # Resolve beat display name — always derive from stem to keep it clean
    beat_name = stem.replace("_", " ").title()
    meta["beat_name"] = beat_name

    # Resolve primary artist from lane config
    if artist:
        meta["seo_artist"] = artist
    elif lane and not meta.get("seo_artist"):
        lane_cfg = _lanes_cfg.get("lanes", {}).get(lane, {})
        if lane_cfg.get("schedule_mode") == "fixed":
            meta["seo_artist"] = lane_cfg.get("slot_artist", "")
        elif lane_cfg.get("schedule_mode") == "rotation":
            rotation = lane_cfg.get("rotation_order", lane_cfg.get("artists", []))
            if rotation:
                meta["seo_artist"] = rotation[0]  # caller can override with specific index

    # Resolve dual artist
    primary = meta.get("seo_artist", "")
    if dual and primary and not meta.get("seo_artist2"):
        partner = _find_dual_partner(primary)
        if partner:
            meta["seo_artist2"] = partner

    # Build YouTube title using lanes template
    meta["title"] = _resolve_title(stem, meta)

    # Store lane info
    if lane:
        meta["lane"] = lane

    meta["artist"] = PRODUCER
    meta["tags"]        = build_tags(stem, meta)
    meta["description"] = build_description(stem, meta)
    return meta


def main():
    parser = argparse.ArgumentParser(description="Generate SEO metadata for beats")
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate metadata even for beats that already have a file"
    )
    parser.add_argument(
        "--only", type=str, default=None,
        help="Comma-separated list of stems to process (default: all)"
    )
    parser.add_argument(
        "--lane", type=str, default=None,
        choices=["breakfast", "lunch", "dinner"],
        help="Assign beats to a specific lane (breakfast/lunch/dinner)"
    )
    parser.add_argument(
        "--artist", type=str, default=None,
        help="Override the SEO artist (e.g. 'GloRilla')"
    )
    parser.add_argument(
        "--dual", action="store_true",
        help="Generate dual-artist title (picks random combo partner)"
    )
    args = parser.parse_args()

    META_DIR.mkdir(exist_ok=True)

    audio_files = sorted(
        list(BEATS_DIR.glob("*.mp3")) + list(BEATS_DIR.glob("*.wav"))
    )

    if not audio_files:
        print(f"[INFO] No audio files found in: {BEATS_DIR}")
        return

    only_stems = set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None

    created = skipped = updated = 0

    for audio_file in audio_files:
        stem = safe_stem(audio_file)

        if only_stems and stem not in only_stems:
            continue

        meta_path = META_DIR / f"{stem}.json"

        if meta_path.exists() and not args.force:
            print(f"[SKIP] {meta_path.name} already exists  (use --force to regenerate)")
            skipped += 1
            continue

        existing = {}
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text())
            except Exception:
                pass

        meta = build_metadata(
            stem, existing,
            lane=args.lane,
            artist=args.artist,
            dual=args.dual,
        )
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        action = "[UPDATE]" if existing else "[META]"
        tag_chars = sum(len(t) + 1 for t in meta["tags"])

        # Show artist info in output
        artist_info = meta.get("seo_artist", "")
        dual_info = f" x {meta['seo_artist2']}" if meta.get("seo_artist2") else ""
        lane_info = f" [{meta['lane']}]" if meta.get("lane") else ""

        print(f"{action} {meta_path.name}  ({len(meta['tags'])} tags, {tag_chars} chars)  "
              f"{artist_info}{dual_info}{lane_info}")
        if existing:
            updated += 1
        else:
            created += 1

    print(f"\nDone: {created} created, {updated} regenerated, {skipped} skipped.")


if __name__ == "__main__":
    main()
