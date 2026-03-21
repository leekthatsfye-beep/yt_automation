"""
AI DJ Service — Intelligent beat-to-artist classification.

Three-layer pipeline:
  Layer 1: Audio feature extraction (librosa via analyze_beats.py --dj)
  Layer 2: Profile matching (numpy distance scoring)
  Layer 3: Claude AI classification (anthropic SDK for ambiguous cases)

Results stored in dj_results.json with approve/reject/override workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.backend.config import PYTHON, ROOT

logger = logging.getLogger(__name__)

PROFILES_PATH = ROOT / "dj_profiles.json"
RESULTS_PATH = ROOT / "dj_results.json"
METADATA_DIR = ROOT / "metadata"
BEATS_DIR = ROOT / "beats"


# ── Profile Loading ─────────────────────────────────────────────────────

def load_profiles() -> dict[str, Any]:
    """Load artist sonic profiles from dj_profiles.json."""
    try:
        if PROFILES_PATH.exists():
            return json.loads(PROFILES_PATH.read_text())
    except Exception as e:
        logger.error("Failed to load DJ profiles: %s", e)
    return {"artists": {}, "weights": {}}


def load_results() -> dict[str, Any]:
    """Load cached DJ results."""
    try:
        if RESULTS_PATH.exists():
            return json.loads(RESULTS_PATH.read_text())
    except Exception as e:
        logger.error("Failed to load DJ results: %s", e)
    return {"analyzed_at": None, "total_analyzed": 0, "results": {}}


def save_results(data: dict) -> None:
    """Save DJ results to disk."""
    try:
        RESULTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error("Failed to save DJ results: %s", e)


# ── Layer 1: Feature Extraction ─────────────────────────────────────────

async def extract_features_for_stem(stem: str) -> dict | None:
    """
    Run analyze_beats.py --dj --only <stem> --force as subprocess.
    Returns the dj_features dict from metadata, or None on error.
    """
    cmd = [
        PYTHON,
        str(ROOT / "analyze_beats.py"),
        "--dj",
        "--only", stem,
        "--force",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            logger.warning("DJ analysis failed for %s: %s", stem, stderr.decode()[:200])
            return None

        # Read features from metadata
        meta_path = METADATA_DIR / f"{stem}.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            return meta.get("dj_features")

    except asyncio.TimeoutError:
        logger.warning("DJ analysis timed out for %s", stem)
    except Exception as e:
        logger.warning("DJ analysis error for %s: %s", stem, e)

    return None


# ── Layer 2: Profile Matching ───────────────────────────────────────────

def _gaussian_score(value: float, center: float, sigma: float) -> float:
    """Gaussian distance score: 100 at center, drops off with distance."""
    return 100 * np.exp(-0.5 * ((value - center) / max(sigma, 0.001)) ** 2)


def _range_score(value: float, lo: float, hi: float, center: float) -> float:
    """Score based on whether value falls within artist's range + distance from center."""
    if lo <= value <= hi:
        # In range — score based on closeness to center
        range_width = max(hi - lo, 0.001)
        sigma = range_width / 2.5  # ~95% of range gets >60 score
        return _gaussian_score(value, center, sigma)
    else:
        # Out of range — penalize heavily
        if value < lo:
            dist = lo - value
        else:
            dist = value - hi
        range_width = max(hi - lo, 0.001)
        return max(0, 100 - (dist / range_width) * 100)


def match_profiles(features: dict, bpm: int, key: str) -> list[dict]:
    """
    Score each artist profile against extracted features.
    Returns list sorted by score (highest first).
    """
    config = load_profiles()
    artists = config.get("artists", {})
    weights = config.get("weights", {})

    if not artists or not features:
        return []

    key_mode = features.get("key_mode", "minor")
    brightness = features.get("brightness_norm", 0.4)
    bass = features.get("bass_energy_ratio", 0.4)
    rms = features.get("rms_mean", 0.08)
    onset = features.get("onset_rate", 7.0)
    bounce = features.get("bounce_factor", 0.4)

    results = []

    for name, profile in artists.items():
        scores = {}

        # BPM fit
        scores["bpm"] = _range_score(
            bpm,
            profile["bpm_range"][0],
            profile["bpm_range"][1],
            profile["bpm_center"],
        )

        # Key mode alignment
        pref = profile.get("key_mode", "minor")
        if pref == "mixed":
            scores["key_mode"] = 80  # no strong preference
        elif key_mode == pref:
            scores["key_mode"] = 100
        else:
            scores["key_mode"] = 30  # mismatch penalty

        # Brightness
        scores["brightness"] = _range_score(
            brightness,
            profile["brightness_range"][0],
            profile["brightness_range"][1],
            profile["brightness_center"],
        )

        # Bass energy
        scores["bass_energy"] = _range_score(
            bass,
            profile["bass_energy_range"][0],
            profile["bass_energy_range"][1],
            profile["bass_center"],
        )

        # Energy (RMS)
        scores["energy"] = _range_score(
            rms,
            profile["energy_range"][0],
            profile["energy_range"][1],
            profile["energy_center"],
        )

        # Onset density
        scores["onset_density"] = _range_score(
            onset,
            profile["onset_density_range"][0],
            profile["onset_density_range"][1],
            profile["onset_center"],
        )

        # Bounce factor
        scores["bounce"] = _range_score(
            bounce,
            profile["bounce_range"][0],
            profile["bounce_range"][1],
            profile["bounce_center"],
        )

        # Weighted total
        total = sum(
            scores.get(dim, 0) * weights.get(dim, 0)
            for dim in weights
        )
        total = min(100, max(0, total))

        results.append({
            "artist": name,
            "score": round(total, 1),
            "lane": profile.get("lane", ""),
            "dimension_scores": {k: round(v, 1) for k, v in scores.items()},
            "source": "profile",
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ── Layer 3: Claude AI Classification ───────────────────────────────────

async def classify_with_ai(
    stem: str,
    features: dict,
    bpm: int,
    key: str,
    profile_scores: list[dict],
) -> dict | None:
    """
    Use Claude Haiku for final classification on ambiguous beats.
    Returns {"artist": str, "confidence": int, "reasoning": str} or None.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping AI classification")
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed, skipping AI classification")
        return None

    # Build the prompt
    top_3 = profile_scores[:3]
    top_3_text = "\n".join(
        f"  {i+1}. {s['artist']} — score {s['score']}/100 "
        f"(bpm={s['dimension_scores'].get('bpm', 0):.0f}, "
        f"brightness={s['dimension_scores'].get('brightness', 0):.0f}, "
        f"bass={s['dimension_scores'].get('bass_energy', 0):.0f}, "
        f"bounce={s['dimension_scores'].get('bounce', 0):.0f})"
        for i, s in enumerate(top_3)
    )

    config = load_profiles()
    artist_desc = "\n".join(
        f"- {name}: {p.get('description', '')}"
        for name, p in config.get("artists", {}).items()
    )

    prompt = f"""You are an expert music producer specializing in trap, drill, and hip-hop beats.
Classify which artist this beat best fits based on its audio features.

Beat: "{stem}"
BPM: {bpm}, Key: {key}
Brightness: {features.get('brightness_norm', 0):.2f} (0=dark, 1=bright)
Bass Energy: {features.get('bass_energy_ratio', 0):.2f} (0=light, 1=heavy)
Energy (RMS): {features.get('rms_mean', 0):.4f}
Bounce Factor: {features.get('bounce_factor', 0):.2f} (0=straight, 1=bouncy)
Onset Density: {features.get('onset_rate', 0):.1f} onsets/sec
Zero Crossing Rate: {features.get('zcr_mean', 0):.4f}

Profile Match Scores:
{top_3_text}

Artist Sonic DNA:
{artist_desc}

Based on the audio features and your expertise, which artist does this beat best fit?
Consider: tempo range, key mode (major=bouncy/party, minor=dark/street), brightness, bass heaviness, bounce factor, and onset density.

Respond in JSON only:
{{"artist": "ArtistName", "confidence": 0-100, "reasoning": "brief 1-2 sentence explanation"}}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON from response
        # Handle cases where response has markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        return {
            "artist": result.get("artist", top_3[0]["artist"]),
            "confidence": min(100, max(0, int(result.get("confidence", 50)))),
            "reasoning": result.get("reasoning", ""),
        }
    except Exception as e:
        logger.warning("AI classification failed for %s: %s", stem, e)
        return None


# ── Full Analysis Pipeline ──────────────────────────────────────────────

async def analyze_beat(
    stem: str,
    metadata_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """
    Full DJ analysis pipeline for a single beat.
    Returns a result dict or None on failure.
    """
    meta_dir = metadata_dir or METADATA_DIR
    meta_path = meta_dir / f"{stem}.json"

    if not meta_path.exists():
        logger.warning("No metadata for %s", stem)
        return None

    meta = json.loads(meta_path.read_text())
    bpm = meta.get("bpm")
    key = meta.get("key", "C Minor")

    # Get or extract features
    features = meta.get("dj_features")
    if not features or force:
        features = await extract_features_for_stem(stem)
        if not features:
            return None

    # Layer 2: Profile matching
    profile_scores = match_profiles(features, bpm or 140, key)
    if not profile_scores:
        return None

    top_artist = profile_scores[0]
    ai_result = None

    # Layer 3: AI classification for ambiguous cases
    if len(profile_scores) >= 2:
        gap = profile_scores[0]["score"] - profile_scores[1]["score"]
        if gap < 10:
            ai_result = await classify_with_ai(
                stem, features, bpm or 140, key, profile_scores
            )

    # Determine final recommendation
    if ai_result:
        final_artist = ai_result["artist"]
        confidence = ai_result["confidence"]
        reasoning = ai_result["reasoning"]
        source = "profile+ai"
    else:
        final_artist = top_artist["artist"]
        confidence = int(top_artist["score"])
        reasoning = ""
        source = "profile"

    return {
        "stem": stem,
        "title": meta.get("title", stem),
        "top_artist": final_artist,
        "confidence": confidence,
        "all_scores": profile_scores[:5],  # top 5
        "features": {
            "bpm": bpm,
            "key": key,
            "brightness_norm": features.get("brightness_norm"),
            "bass_energy_ratio": features.get("bass_energy_ratio"),
            "bounce_factor": features.get("bounce_factor"),
            "onset_rate": features.get("onset_rate"),
            "rms_mean": features.get("rms_mean"),
        },
        "ai_reasoning": reasoning,
        "source": source,
        "status": "pending",
        "current_artist": meta.get("seo_artist", ""),
        "current_lane": meta.get("lane", ""),
    }


async def analyze_batch(
    stems: list[str] | None = None,
    metadata_dir: Path | None = None,
    force: bool = False,
    progress_callback=None,
) -> dict[str, Any]:
    """
    Analyze a batch of beats. If stems is None, analyze all beats.
    Returns the full results dict.
    """
    import re

    meta_dir = metadata_dir or METADATA_DIR
    beats_dir = BEATS_DIR

    # Get all stems
    if stems:
        all_stems = stems
    else:
        audio_files = sorted(
            list(beats_dir.glob("*.mp3")) + list(beats_dir.glob("*.wav"))
        )
        def _safe_stem(p: Path) -> str:
            s = p.stem.strip().lower()
            s = re.sub(r"[^\w\s-]", "", s)
            s = re.sub(r"[\s-]+", "_", s)
            return s.strip("_")
        all_stems = [_safe_stem(f) for f in audio_files]

    # Load existing results to preserve statuses
    existing = load_results()
    existing_results = existing.get("results", {})

    total = len(all_stems)
    analyzed = 0

    for i, stem in enumerate(all_stems):
        # Skip already approved/overridden unless forced
        if not force and stem in existing_results:
            status = existing_results[stem].get("status", "pending")
            if status in ("approved", "overridden"):
                continue

        if progress_callback:
            await progress_callback(
                pct=int((i / max(total, 1)) * 100),
                detail=f"Analyzing {stem}... ({i+1}/{total})",
            )

        result = await analyze_beat(stem, meta_dir, force=force)
        if result:
            existing_results[stem] = result
            analyzed += 1

    # Save
    data = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "total_analyzed": len(existing_results),
        "results": existing_results,
    }
    save_results(data)

    if progress_callback:
        await progress_callback(pct=100, detail=f"Done! Analyzed {analyzed} beats")

    return data


# ── Apply/Reject/Override ───────────────────────────────────────────────

def apply_classification(
    stem: str,
    artist: str,
    lane: str,
    metadata_dir: Path | None = None,
) -> bool:
    """
    Apply a DJ classification: update metadata with lane + seo_artist,
    then regenerate SEO metadata.
    """
    meta_dir = metadata_dir or METADATA_DIR
    meta_path = meta_dir / f"{stem}.json"

    if not meta_path.exists():
        return False

    try:
        meta = json.loads(meta_path.read_text())
        meta["lane"] = lane
        meta["seo_artist"] = artist
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

        # Regenerate SEO
        import sys
        sys.path.insert(0, str(ROOT))
        from seo_metadata import build_metadata
        updated = build_metadata(stem, existing=meta, lane=lane, artist=artist)
        meta_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False))

        # Update results
        results = load_results()
        if stem in results.get("results", {}):
            results["results"][stem]["status"] = "approved"
            results["results"][stem]["applied_artist"] = artist
            save_results(results)

        return True
    except Exception as e:
        logger.error("Failed to apply classification for %s: %s", stem, e)
        return False


def reject_classification(stem: str) -> bool:
    """Mark a classification as rejected."""
    results = load_results()
    if stem in results.get("results", {}):
        results["results"][stem]["status"] = "rejected"
        save_results(results)
        return True
    return False


def override_classification(
    stem: str,
    artist: str,
    lane: str,
    metadata_dir: Path | None = None,
) -> bool:
    """Override a classification with a user-chosen artist."""
    # Apply the override
    success = apply_classification(stem, artist, lane, metadata_dir)
    if success:
        results = load_results()
        if stem in results.get("results", {}):
            results["results"][stem]["status"] = "overridden"
            results["results"][stem]["top_artist"] = artist
            results["results"][stem]["applied_artist"] = artist
            save_results(results)
    return success
