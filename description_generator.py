from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT          = Path(__file__).resolve().parent
META_DIR      = ROOT / "metadata"
DESCRIPTIONS  = ROOT / "descriptions"
LANES_CFG     = ROOT / "lanes_config.json"
STORE_LOG     = ROOT / "store_uploads_log.json"

def _load_cfg() -> dict:
    try:
        if LANES_CFG.exists():
            return json.loads(LANES_CFG.read_text())
    except Exception:
        pass
    return {}

_cfg             = _load_cfg()
PRODUCER         = _cfg.get("producer", "leekthatsfy3")
PRODUCER_DISPLAY = _cfg.get("producer_display", "LeekThatsFy3")
STORE_URL        = _cfg.get("store_profile_url", "https://leekthatsfy3.infinity.airbit.com/")
CONTACT_IG       = _cfg.get("contact", "@leekthatsfy3")
YEAR             = _cfg.get("year", 2026)
BRAND_TAG        = "leekthatsfye"

PRICE_MP3       = "$29"
PRICE_WAV       = "$59"
PRICE_UNLIMITED = "$179"
BUNDLE_3        = "$149"
BUNDLE_5        = "$249"

PLAYLISTS: dict[str, str] = {
    "glokk40spaz": "https://www.youtube.com/playlist?list=GLOKK40SPAZ_ID",
    "sexyy red":   "https://www.youtube.com/playlist?list=SEXYYRED_ID",
    "glorilla":    "https://www.youtube.com/playlist?list=GLORILLA_ID",
    "ola runt":    "https://www.youtube.com/playlist?list=OLARUNT_ID",
    "biggkutt8":   "https://www.youtube.com/playlist?list=BIGGKUTT8_ID",
    "_default":    "https://www.youtube.com/playlist?list=FY3_ALL_BEATS_ID",
}

_SKIP = {
    "dark", "melodic", "hard", "emotional", "aggressive", "chill", "sad",
    "trap", "drill", "wave", "bounce", "vibe", "free", "beat", "beats",
}

def _load_meta(stem: str) -> dict:
    p = META_DIR / f"{stem}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}

def _beat_url(stem: str) -> str:
    try:
        if STORE_LOG.exists():
            data = json.loads(STORE_LOG.read_text())
            entry = data.get(stem, {})
            url = entry.get("airbit", {}).get("url") or entry.get("url")
            if url:
                return url
    except Exception:
        pass
    return STORE_URL

def _artist(meta: dict) -> str:
    return meta.get("seo_artist") or meta.get("artist") or ""

def _playlist(artist: str) -> str:
    return PLAYLISTS.get(artist.lower().strip(), PLAYLISTS["_default"])

def _build_tags(artist: str, meta: dict) -> list[str]:
    tags: list[str] = []
    if artist:
        slug = artist.lower().replace(" ", "")
        tags += [f"#{slug}typebeat", f"#{slug}instrumental"]
    for t in meta.get("tags", []):
        if t.lower() in _SKIP:
            continue
        tags.append(f"#{t.lower().replace(' ', '')}")
        if len(tags) >= 10:
            break
    tags += [f"#{PRODUCER}", f"#{BRAND_TAG}", "#typebeat", f"#typebeat{YEAR}"]
    return tags[:15]

def generate_title(stem: str, meta: dict | None = None) -> str:
    if meta is None:
        meta = _load_meta(stem)
    artist = _artist(meta)
    name   = meta.get("beat_name") or stem.replace("_", " ").title()
    if meta.get("seo_artist2"):
        a2 = meta["seo_artist2"]
        return f'{artist} x {a2} Type Beat - "{name}"'
    if artist:
        return f'{artist} Type Beat - "{name}"'
    return f'Type Beat - "{name}"'

def generate_description(stem: str, meta: dict | None = None) -> str:
    if meta is None:
        meta = _load_meta(stem)
    artist   = _artist(meta)
    url      = _beat_url(stem)
    playlist = _playlist(artist)
    tags     = _build_tags(artist, meta)
    D        = "\u2500" * 38

    lines = [
        "\U0001f3a7 Purchase This Beat",
        url,
        "Use this for your next drop \U0001f525",
        "No copyright \u2014 ready for release",
        "",
        f"\U0001f525 3 Beats for {BUNDLE_3} (WAV) \u2014 Save money vs buying 1 (most popular)",
        STORE_URL,
        "",
        "More Beats Like This",
        playlist,
        "If this fits your sound, I got more like this \u2014 stay locked in",
        "",
        D,
        "",
        f"MP3 {PRICE_MP3} | WAV {PRICE_WAV} \u2b50 | Unlimited {PRICE_UNLIMITED}",
        "Most artists go with WAV or the 3-pack \u2014 best value.",
        "Ready to drop? Grab it above \u2b06\ufe0f",
        "",
        f"DM on IG: {CONTACT_IG}",
        f"prod. {PRODUCER}",
        f"\u00a9 {YEAR} {PRODUCER_DISPLAY}",
        "",
        D,
        "",
        " ".join(tags),
    ]

    desc = "\n".join(lines).strip()
    while len(desc) > 5000 and tags:
        tags.pop()
        lines[-1] = " ".join(tags)
        desc = "\n".join(lines).strip()
    return desc

def generate_comment(stem: str) -> str:
    url = _beat_url(stem)
    return (
        f"Artists \u2014 grab this beat here:\n{url}\n\n"
        f"\U0001f525 3 Beats for {BUNDLE_3}\n"
        f"Most artists grab bundles to stay consistent\n"
        f"DM me for bundles or custom beats"
    )

def build_upload_package(stem: str) -> dict:
    meta   = _load_meta(stem)
    artist = _artist(meta)
    return {
        "title":       generate_title(stem, meta),
        "description": generate_description(stem, meta),
        "comment":     generate_comment(stem),
        "tags":        _build_tags(artist, meta),
    }

def generate_all(save: bool = False) -> dict[str, dict]:
    results: dict[str, dict] = {}
    files = sorted(META_DIR.glob("*.json"))
    if not files:
        print("[WARN] No metadata files found.")
        return results
    if save:
        DESCRIPTIONS.mkdir(exist_ok=True)
    for p in files:
        stem = p.stem
        try:
            meta = json.loads(p.read_text())
            pkg  = build_upload_package(stem)
            results[stem] = pkg
            if save:
                out = DESCRIPTIONS / f"{stem}.txt"
                out.write_text(
                    f"TITLE\n{pkg['title']}\n\n"
                    f"DESCRIPTION\n{pkg['description']}\n\n"
                    f"COMMENT\n{pkg['comment']}\n",
                    encoding="utf-8",
                )
                print(f"[SAVED] {out.name}")
            else:
                print(f"[OK]    {stem}")
        except Exception as e:
            print(f"[ERR]   {stem} \u2014 {e}")
    return results

def main() -> None:
    parser = argparse.ArgumentParser(description="FY3 Upload Package Generator")
    parser.add_argument("--stem",  "-s", help="Single beat stem (e.g. hood_legend)")
    parser.add_argument("--all",   action="store_true", help="Process all beats in metadata/")
    parser.add_argument("--save",  action="store_true", help="Save output to descriptions/")
    parser.add_argument("--json",  action="store_true", help="Print as JSON")
    args = parser.parse_args()

    if args.all:
        results = generate_all(save=args.save)
        if args.json and not args.save:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        elif not args.save:
            for stem, pkg in results.items():
                _print_package(stem, pkg)
        print(f"\n\u2705  {len(results)} packages generated.")
        return

    if not args.stem:
        print("[ERR] Provide --stem STEM  or  --all")
        sys.exit(1)

    pkg = build_upload_package(args.stem.strip().lower())

    if args.json:
        print(json.dumps(pkg, indent=2, ensure_ascii=False))
    elif args.save:
        DESCRIPTIONS.mkdir(exist_ok=True)
        out = DESCRIPTIONS / f"{args.stem}.txt"
        out.write_text(
            f"TITLE\n{pkg['title']}\n\n"
            f"DESCRIPTION\n{pkg['description']}\n\n"
            f"COMMENT\n{pkg['comment']}\n",
            encoding="utf-8",
        )
        print(f"[SAVED] {out}")
    else:
        _print_package(args.stem, pkg)

def _print_package(stem: str, pkg: dict) -> None:
    W = 55
    print(f"\n{'='*W}\n  {stem}\n{'='*W}")
    print(f"\nTITLE\n{pkg['title']}")
    print(f"\nDESCRIPTION\n{pkg['description']}")
    print(f"\nCOMMENT\n{pkg['comment']}")
    print(f"\nTAGS\n{' '.join(pkg['tags'])}")
    print(f"\n[{len(pkg['description'])} / 5000 chars]\n")

if __name__ == "__main__":
    main()
