"""
make_shorts.py — batch generate 9x16 shorts for NextBatch beats.
Runs convert_to_portrait() with force=True so new hooks are applied.
Usage: python make_shorts.py
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from social_upload import convert_to_portrait

NEXTBATCH = [
    'dawg_food_142', 'glory', 'karate_chop_145', 'kill_3m', 'lick',
    'lonely_child', 'manhunt', 'ngga', 'ny', 'ocean_drive_145',
    'grown_man_shit', 'on_55555', 'playa', 'raise_da_price', 'revenge',
    'rio', 'rku', 'sauce_165', 'schmell_me', 'screeet', 'shake_ya_ass_ho3',
    'sight', 'souljaz', 'starvin', 'state_of_emergency', 'stayed_down',
    'steamer', 'street_pharmacy', 'sum_jerk_type', 'super_smash_hoez',
    'tag_em', 'thug_life', 'time', 'tru3', 'uav', 'walk_ups', 'wav',
    'whack_em', 'wheres_my_money', 'hartfield_jackson', '2xdxrt3all_gen_5',
]

OUT_DIR = Path(__file__).resolve().parent / "output"

done = 0
failed = 0
skipped = 0

print(f"\n{'─'*50}")
print(f"  make_shorts.py — {len(NEXTBATCH)} beats")
print(f"{'─'*50}\n")

for stem in NEXTBATCH:
    mp4 = OUT_DIR / "renders" / f"{stem}.mp4"
    if not mp4.exists():
        print(f"[SKIP] {stem} — full render not found yet")
        skipped += 1
        continue
    try:
        print(f"[SHORT] {stem}")
        convert_to_portrait(stem, force=True)
        done += 1
        print(f"[DONE]  {stem}")
    except Exception as e:
        print(f"[FAIL]  {stem}: {e}")
        failed += 1

print(f"\n{'─'*50}")
print(f"  Done: {done}  Failed: {failed}  Skipped: {skipped}")
print(f"{'─'*50}\n")
