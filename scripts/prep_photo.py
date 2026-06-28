"""
prep_photo.py — auto-select a drop's photo from the crew library and cut a
cartier-style (full-fit, NO logo, NO text) thumbnail. The "never pick a photo
manually again" step.

Flow per drop:
  prep_photo.py --only <stem>     # reads metadata seo_artist, picks the photo,
                                  # writes images/<stem>.jpg + output/<stem>_thumb.jpg
  render_lit.py --only <stem>     # renders video; sees the thumb exists -> keeps it

Photo priority (crew_photos.pick): _crew/<Artist>/hero.jpg  >  sharpest CLEAN
(text-free, well-lit) scraped pic. Drop a hero.jpg per artist to guarantee the
money shot; auto-pick is the fallback.

  --artist "Name"   override the artist folder
  --preview         don't touch images/; write thumb to output/<stem>_thumb_preview.jpg
"""
import os, sys, json, shutil, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crew_photos
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def folder_name(artist):
    # seo_artist may be "Diamond*"/"Diamønd" — crew folders are plain ("Diamond")
    return artist.replace("*", "").replace("ø", "o").replace("Ø", "O").strip()

def cartier_thumb(src, out):
    """Full fit-pic on black (pillarbox) — no logo, no text. 1280x720."""
    im = Image.open(src).convert("RGB"); w, h = im.size
    W, H = 1280, 720
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    if w / h <= W / H:                      # taller than 16:9 -> fit height, bars L/R
        nw = int(w * (H / h)); canvas.paste(im.resize((nw, H)), ((W - nw) // 2, 0))
    else:                                   # wider -> fit width, bars top/bottom
        nh = int(h * (W / w)); canvas.paste(im.resize((W, nh)), (0, (H - nh) // 2))
    canvas.save(out, quality=90)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", required=True, help="beat stem")
    ap.add_argument("--artist", default=None)
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    stem = a.only
    artist = a.artist
    if not artist:
        meta_p = os.path.join(ROOT, "metadata", f"{stem}.json")
        if not os.path.exists(meta_p):
            print(f"[ERR] no metadata/{stem}.json and no --artist given"); return
        artist = json.load(open(meta_p, encoding="utf-8")).get("seo_artist", "")
    fol = folder_name(artist)
    # real drop consumes the rotation (commit); --preview just peeks (no commit)
    pic = crew_photos.pick(fol, seed=stem, commit=not a.preview)
    if not pic:
        print(f"[ERR] no clean photo found for '{fol}' in _crew/ — add a hero.jpg"); return
    src_tag = "hero" if os.path.basename(pic).lower().startswith("hero") else "auto-pick"
    print(f"[PHOTO] {stem}: {fol} -> {os.path.basename(pic)} ({src_tag})")
    if a.preview:
        out = os.path.join(ROOT, "output", f"{stem}_thumb_preview.jpg")
        cartier_thumb(pic, out); print(f"[PREVIEW] {out}"); return
    img = os.path.join(ROOT, "images", f"{stem}.jpg")
    shutil.copy(pic, img); print(f"[SET] images/{stem}.jpg")
    thumb = os.path.join(ROOT, "output", f"{stem}_thumb.jpg")
    cartier_thumb(pic, thumb); print(f"[THUMB] output/{stem}_thumb.jpg (cartier-style, no logo)")

if __name__ == "__main__":
    main()
