"""
crew_photos.py — clean-shot selection for OWAY crew fit-pics.

- has_text(path): True if the image has overlay / title / lyric text (rejects it).
  Uses Tesseract OCR on an upscaled grayscale variant. Catches readable + graphic
  text; very stylized graffiti-logo fonts can slip (rare in official MV thumbs).
- sharpness(path): Laplacian-variance focus score (higher = sharper).
- pick(artist): the photo to use for a drop — hero.jpg if present, else the
  SHARPEST clean (text-free) pic in the artist's _crew folder. None if folder empty.
- clean_folder(artist): delete text-having pics from an artist folder.

Used by scripts/scrape_crew_pics.py (filter on download) and scripts/prep_photo.py
(auto-pick the drop photo by artist).
"""
import os, glob, json, random
import numpy as np
from PIL import Image, ImageOps

CREW_BASE = r"C:\Users\fy3ma\Dropbox\0way !\_crew"
_USED = os.path.join(CREW_BASE, "_used.json")  # rotation tracker: artist -> [used filenames]

def _load_used():
    try:
        return json.load(open(_USED, encoding="utf-8"))
    except Exception:
        return {}

def _save_used(d):
    try:
        json.dump(d, open(_USED, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass
_TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

_pt = None
def _ocr():
    global _pt
    if _pt is None:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = _TESS
        _pt = pytesseract
    return _pt

def has_text(path):
    """True = image carries overlay/title/lyric text → reject as 'not a clean shot'.
    Rule: >=2 confident multi-char words, OR any single large text block
    (height > 8.5% of frame = an overlay title). Tolerates 1 tiny incidental
    background word (e.g. a storefront sign) so clean fits aren't over-rejected."""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return False
    g = ImageOps.autocontrast(ImageOps.grayscale(im))
    W, H = g.size
    g = g.resize((W * 2, H * 2))
    vh = g.size[1]
    pt = _ocr()
    try:
        d = pt.image_to_data(g, config="--psm 11", output_type=pt.Output.DICT)
    except Exception:
        return False
    words = big = 0
    for i, t in enumerate(d["text"]):
        t = t.strip()
        alnum = sum(c.isalnum() for c in t)
        if alnum >= 3 and float(d["conf"][i]) > 55:
            words += 1
            if d["height"][i] > vh * 0.085:
                big += 1
    return big >= 1 or words >= 2

def sharpness(path):
    """Laplacian variance — higher = sharper / less motion blur."""
    try:
        a = np.asarray(Image.open(path).convert("L").resize((480, 270)), dtype=np.float64)
    except Exception:
        return 0.0
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:])
    return float(lap.var())

def quality(path):
    """Thumbnail quality = sharpness weighted by exposure, so a SHARP-but-silhouette
    frame (busy bright background, subject in shadow) doesn't beat a well-lit shot."""
    try:
        a = np.asarray(Image.open(path).convert("L").resize((480, 270)), dtype=np.float64)
    except Exception:
        return 0.0
    L = a.mean()                                   # overall brightness
    Lc = a[68:202, 120:360].mean()                 # center region (subject sits here)
    w = 1.0
    if L < 40 or L > 222:   w *= 0.10              # too dark / blown out
    if Lc < 55:             w *= 0.20              # subject in shadow/silhouette
    elif Lc > 230:          w *= 0.50              # subject blown out
    return sharpness(path) * w

def _folder(artist):
    return os.path.join(CREW_BASE, artist)

def clean_folder(artist):
    """Delete text-bearing pics; return (kept, removed)."""
    removed = kept = 0
    for p in glob.glob(os.path.join(_folder(artist), "*.jpg")):
        if os.path.basename(p).lower().startswith("hero"):
            kept += 1
            continue
        if has_text(p):
            try: os.remove(p); removed += 1
            except Exception: kept += 1
        else:
            kept += 1
    return kept, removed

def pick(artist, seed=None, commit=False):
    """ROTATION: return a pic this artist hasn't used yet — fresh every video,
    no repeats until the whole pool has been cycled, then it resets.

    Folders are text-filtered on scrape (no re-OCR here). We drop the bottom ~20%
    by quality so junk never rotates in, then choose among the UNUSED pics.
    `seed` (the beat stem) keeps a preview == its final render.
    `commit=True` records the pic as used (call on the real drop, not on preview).
    A manually-placed hero.jpg/png still overrides if you ever want a lock.
    """
    folder = _folder(artist)
    for ext in ("hero.jpg", "hero.png", "hero.jpeg"):
        h = os.path.join(folder, ext)
        if os.path.exists(h):
            return h
    cands = [p for p in glob.glob(os.path.join(folder, "*.jpg"))
             if not os.path.basename(p).lower().startswith("hero")]
    if not cands:
        return None
    scored = sorted(cands, key=quality, reverse=True)
    eligible = scored[:max(8, int(len(scored) * 0.8))]      # skip bottom 20% (junk)

    used_all = _load_used()
    used = set(used_all.get(artist, []))
    fresh = [p for p in eligible if os.path.basename(p) not in used]
    if not fresh:                                           # full cycle done -> reset
        used = set()
        fresh = eligible
    rng = random.Random(seed) if seed is not None else random
    choice = rng.choice(fresh)

    if commit:
        used.add(os.path.basename(choice))
        used_all[artist] = sorted(used)
        _save_used(used_all)
    return choice
