"""
Channel Integrity Manager — daily audit for channel health.

Scans all beats and uploads to detect issues:
- Missing purchase links in descriptions
- Missing or insufficient tags
- Incorrect title formatting
- Missing lane/artist assignments
- Beats uploaded to YouTube but not rendered properly
- Metadata inconsistencies
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def run_integrity_audit(
    beats_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
    uploads_log_path: Path,
) -> dict[str, Any]:
    """Run a comprehensive channel integrity audit.

    Returns a Channel Health Report with issues and recommendations.
    """
    import re

    def safe_stem(name: str) -> str:
        s = name.rsplit(".", 1)[0].strip().lower()
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"[\s-]+", "_", s)
        return s.strip("_")

    uploads_log = _load_json(uploads_log_path)

    # Collect all beats
    audio_files = list(beats_dir.glob("*.mp3")) + list(beats_dir.glob("*.wav"))
    all_stems = {safe_stem(f.name) for f in audio_files}

    issues: list[dict[str, Any]] = []
    stats = {
        "total_beats": len(all_stems),
        "total_uploaded": 0,
        "missing_metadata": 0,
        "missing_purchase_link": 0,
        "incorrect_title": 0,
        "missing_tags": 0,
        "low_tag_count": 0,
        "missing_lane": 0,
        "missing_seo_artist": 0,
        "missing_producer_credit": 0,
        "not_rendered": 0,
        "rendered_not_uploaded": 0,
        "contains_free_tags": 0,
    }

    for stem in sorted(all_stems):
        meta_path = metadata_dir / f"{stem}.json"
        has_render = (output_dir / f"{stem}.mp4").exists()
        is_uploaded = stem in uploads_log

        if is_uploaded:
            stats["total_uploaded"] += 1

        # Check metadata exists
        if not meta_path.exists():
            stats["missing_metadata"] += 1
            issues.append({
                "stem": stem,
                "severity": "high",
                "issue": "missing_metadata",
                "message": f"No metadata file for {stem}",
                "action": "Run seo_metadata.py to generate metadata",
            })
            continue

        meta = _load_json(meta_path)

        # Check title format
        title = meta.get("title", "")
        if title and "Type Beat" not in title:
            stats["incorrect_title"] += 1
            issues.append({
                "stem": stem,
                "severity": "medium",
                "issue": "incorrect_title",
                "message": f"Title missing 'Type Beat': {title}",
                "action": "Regenerate SEO metadata with --force",
            })

        # Check tags
        tags = meta.get("tags", [])
        if not tags:
            stats["missing_tags"] += 1
            issues.append({
                "stem": stem,
                "severity": "high",
                "issue": "missing_tags",
                "message": f"No tags for {stem}",
                "action": "Regenerate SEO metadata",
            })
        elif len(tags) < 8:
            stats["low_tag_count"] += 1
            issues.append({
                "stem": stem,
                "severity": "low",
                "issue": "low_tag_count",
                "message": f"Only {len(tags)} tags (need 8+)",
                "action": "Regenerate SEO metadata with --force",
            })

        # Check for free tags
        if any("free" in t.lower() for t in tags):
            stats["contains_free_tags"] += 1
            issues.append({
                "stem": stem,
                "severity": "medium",
                "issue": "contains_free_tags",
                "message": "Tags contain 'free' keyword",
                "action": "Regenerate SEO metadata to remove free tags",
            })

        # Check description
        desc = meta.get("description", "")
        if "AIRBIT" not in desc.upper() and "airbit" not in desc.lower() and "Purchase" not in desc:
            stats["missing_purchase_link"] += 1
            issues.append({
                "stem": stem,
                "severity": "high",
                "issue": "missing_purchase_link",
                "message": "Description missing purchase/Airbit link",
                "action": "Update description with purchase funnel",
            })

        if "prod." not in desc.lower() and "leekthatsfy3" not in desc.lower():
            stats["missing_producer_credit"] += 1
            issues.append({
                "stem": stem,
                "severity": "low",
                "issue": "missing_producer_credit",
                "message": "Description missing producer credit",
                "action": "Add prod. leekthatsfy3 to description",
            })

        # Check lane assignment
        if not meta.get("lane"):
            stats["missing_lane"] += 1
            issues.append({
                "stem": stem,
                "severity": "low",
                "issue": "missing_lane",
                "message": "No lane assigned",
                "action": "Assign to breakfast/lunch/dinner lane",
            })

        # Check SEO artist
        if not meta.get("seo_artist"):
            stats["missing_seo_artist"] += 1
            issues.append({
                "stem": stem,
                "severity": "medium",
                "issue": "missing_seo_artist",
                "message": "No SEO artist assigned",
                "action": "Assign SEO artist for tag optimization",
            })

        # Check render status
        if not has_render:
            stats["not_rendered"] += 1

        # Check uploaded but not rendered (shouldn't happen but...)
        if is_uploaded and not has_render:
            issues.append({
                "stem": stem,
                "severity": "low",
                "issue": "uploaded_no_render",
                "message": "Uploaded to YouTube but render file missing locally",
                "action": "Re-render video",
            })

        # Rendered but not uploaded
        if has_render and not is_uploaded:
            stats["rendered_not_uploaded"] += 1

    # Calculate health score (0-100)
    total = max(stats["total_beats"], 1)
    high_issues = sum(1 for i in issues if i["severity"] == "high")
    medium_issues = sum(1 for i in issues if i["severity"] == "medium")
    low_issues = sum(1 for i in issues if i["severity"] == "low")

    penalty = (high_issues * 3 + medium_issues * 1.5 + low_issues * 0.5)
    max_penalty = total * 3  # worst case: every beat has a high issue
    health_score = max(0, int(100 - (penalty / max(max_penalty, 1)) * 100))

    return {
        "health_score": health_score,
        "health_level": "good" if health_score >= 80 else "warning" if health_score >= 60 else "critical",
        "stats": stats,
        "issues": issues,
        "issue_summary": {
            "high": high_issues,
            "medium": medium_issues,
            "low": low_issues,
            "total": len(issues),
        },
    }
