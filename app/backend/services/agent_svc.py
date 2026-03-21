"""
AI Producer Agent — natural language command interpreter + task executor.

Parses producer commands and routes them to the correct automation module.
Now EXECUTES commands directly instead of just returning data.
Supports commands like:
  "render army"
  "upload all beats"
  "generate seo for everything"
  "schedule next 5 uploads"
  "scan channel health"
  "find revive candidates"
  "recommend next uploads"
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Command patterns → module routing ────────────────────────────────────

COMMAND_MAP: list[dict[str, Any]] = [
    {
        "patterns": [r"scan\s+channel\s+health", r"channel\s+health", r"audit\s+channel", r"health\s+report", r"integrity"],
        "module": "integrity",
        "action": "audit",
        "description": "Run channel integrity audit",
        "executes": True,
    },
    {
        "patterns": [r"reviv(e|al)", r"old\s+videos", r"regain\s+traffic", r"revive\s+candidates"],
        "module": "revival",
        "action": "scan",
        "description": "Scan for catalog revival candidates",
        "executes": True,
    },
    {
        "patterns": [r"trend", r"trending", r"discover", r"what.+upload\s+next", r"recommend"],
        "module": "trends",
        "action": "recommend",
        "description": "Get trending artist recommendations",
        "executes": True,
    },
    {
        "patterns": [r"generate\s+seo", r"seo\s+metadata", r"metadata\s+for"],
        "module": "seo",
        "action": "generate",
        "description": "Generate SEO metadata for beats",
        "executes": True,
    },
    {
        "patterns": [r"render\s+video", r"render\s+beat", r"render\s+all", r"make\s+video", r"render\s+(\w+)"],
        "module": "render",
        "action": "render",
        "description": "Render beat videos",
        "executes": True,
    },
    {
        "patterns": [r"upload\s+to\s+youtube", r"upload\s+beat", r"upload\s+all", r"youtube\s+upload", r"upload\s+(\w+)"],
        "module": "upload",
        "action": "upload",
        "description": "Upload videos to YouTube",
        "executes": True,
    },
    {
        "patterns": [r"schedule\s+(\d+)", r"schedule\s+next", r"schedule\s+upload", r"queue\s+upload", r"plan\s+upload"],
        "module": "schedule",
        "action": "schedule",
        "description": "Schedule uploads",
        "executes": True,
    },
    {
        "patterns": [r"airbit", r"sync\s+store", r"beat\s+store", r"sync\s+airbit"],
        "module": "airbit",
        "action": "sync",
        "description": "Sync beats with Airbit store",
        "executes": True,
    },
    {
        "patterns": [r"post\s+to\s+social", r"post\s+to\s+instagram", r"post\s+to\s+tiktok", r"post\s+shorts"],
        "module": "social",
        "action": "post",
        "description": "Post to social media",
        "executes": True,
    },
    {
        "patterns": [r"analytics", r"stats", r"how.+channel\s+doing", r"performance"],
        "module": "analytics",
        "action": "report",
        "description": "Get analytics report",
        "executes": True,
    },
    {
        "patterns": [r"assign\s+lane", r"lane\s+assign", r"set\s+lane", r"assign\s+(\w+)\s+to\s+(breakfast|lunch|dinner)"],
        "module": "lanes",
        "action": "assign",
        "description": "Assign beats to lanes",
        "executes": True,
    },
    {
        "patterns": [r"scan\s+youtube", r"youtube\s+scan", r"scan\s+trends"],
        "module": "trends",
        "action": "scan",
        "description": "Scan YouTube for fresh trend data",
        "executes": True,
    },
    {
        "patterns": [r"help", r"what\s+can\s+you\s+do", r"commands"],
        "module": "agent",
        "action": "help",
        "description": "Show available commands",
        "executes": False,
    },
]


def interpret_command(text: str) -> dict[str, Any]:
    """Parse a natural language command and route it to the correct module.

    Returns:
        {
            "understood": bool,
            "module": str,
            "action": str,
            "description": str,
            "params": dict,  # extracted parameters
            "original": str,
            "executes": bool,
        }
    """
    text_lower = text.strip().lower()

    # Try to match against known patterns
    for cmd in COMMAND_MAP:
        for pattern in cmd["patterns"]:
            match = re.search(pattern, text_lower)
            if match:
                # Extract parameters
                params = _extract_params(text_lower, cmd["module"], match)

                return {
                    "understood": True,
                    "module": cmd["module"],
                    "action": cmd["action"],
                    "description": cmd["description"],
                    "params": params,
                    "original": text,
                    "executes": cmd.get("executes", False),
                }

    # No match
    return {
        "understood": False,
        "module": None,
        "action": None,
        "description": "Command not recognized",
        "params": {},
        "original": text,
        "suggestions": _suggest_commands(text_lower),
    }


def _extract_params(text: str, module: str, match: re.Match | None = None) -> dict[str, Any]:
    """Extract parameters from the command text."""
    params: dict[str, Any] = {}

    # Extract artist names
    artist_match = re.search(r"for\s+([A-Za-z0-9\s]+?)(?:\s+beats?|\s*$)", text)
    if artist_match:
        params["artist"] = artist_match.group(1).strip().title()

    # Extract lane
    lane_match = re.search(r"(breakfast|lunch|dinner)\s*(?:lane)?", text)
    if lane_match:
        params["lane"] = lane_match.group(1)

    # Extract count
    count_match = re.search(r"(\d+)\s+(?:beat|video|upload)", text)
    if count_match:
        params["count"] = int(count_match.group(1))

    # Also try "schedule next 5" or "schedule 3"
    sched_count = re.search(r"schedule\s+(?:next\s+)?(\d+)", text)
    if sched_count and "count" not in params:
        params["count"] = int(sched_count.group(1))

    # Extract "all" keyword
    if "all" in text.split():
        params["all"] = True

    # Extract stems (comma-separated or single word after command verb)
    stems_match = re.search(r"(?:only|stems?)\s+([a-z0-9_,\s]+)", text)
    if stems_match:
        stems = [s.strip() for s in stems_match.group(1).split(",") if s.strip()]
        if stems:
            params["stems"] = stems

    # Try to extract a single stem from "render army" or "upload hood_legend"
    if "stems" not in params:
        single_stem_patterns = [
            r"(?:render|upload|generate\s+seo\s+for|post)\s+([a-z0-9_]+)",
        ]
        for pat in single_stem_patterns:
            m = re.search(pat, text)
            if m:
                stem = m.group(1).strip()
                if stem not in ("all", "video", "beat", "beats", "seo", "to", "youtube", "channel", "next", "social"):
                    params["stems"] = [stem]
                    break

    # Extract privacy
    privacy_match = re.search(r"(public|unlisted|private)", text)
    if privacy_match:
        params["privacy"] = privacy_match.group(1)

    # Extract platform for social
    for platform in ("instagram", "tiktok", "shorts", "ig"):
        if platform in text:
            params["platform"] = "ig" if platform == "instagram" else platform
            break

    return params


def _suggest_commands(text: str) -> list[str]:
    """Suggest similar commands when input isn't recognized."""
    suggestions = [
        "render all beats",
        "render army",
        "upload all beats",
        "generate seo for all beats",
        "schedule next 5 uploads",
        "scan channel health",
        "find revival candidates",
        "recommend next uploads",
        "scan youtube trends",
        "post to instagram",
        "show analytics",
    ]

    # Simple keyword matching for suggestions
    words = set(text.split())
    scored = []
    for cmd in suggestions:
        cmd_words = set(cmd.split())
        overlap = len(words & cmd_words)
        if overlap > 0:
            scored.append((overlap, cmd))

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [cmd for _, cmd in scored[:3]]

    return suggestions[:5]


def get_available_commands() -> list[dict[str, str]]:
    """Return all available commands with descriptions and examples."""
    return [
        {"command": "render all beats", "module": "render", "description": "Render all unrendered beats to MP4"},
        {"command": "render [beat_name]", "module": "render", "description": "Render a specific beat"},
        {"command": "upload all beats", "module": "upload", "description": "Upload all rendered beats to YouTube"},
        {"command": "upload [beat_name]", "module": "upload", "description": "Upload a specific beat to YouTube"},
        {"command": "generate seo for all beats", "module": "seo", "description": "Generate SEO metadata for all beats"},
        {"command": "generate seo for [beat_name]", "module": "seo", "description": "Generate SEO for a specific beat"},
        {"command": "schedule next 5 uploads", "module": "schedule", "description": "Schedule the next N uploads"},
        {"command": "scan youtube trends", "module": "trends", "description": "Pull fresh YouTube demand data"},
        {"command": "recommend next uploads", "module": "trends", "description": "Get trending artist recommendations"},
        {"command": "scan channel health", "module": "integrity", "description": "Run channel integrity audit"},
        {"command": "find revival candidates", "module": "revival", "description": "Find old uploads to refresh"},
        {"command": "post to instagram", "module": "social", "description": "Post a beat to Instagram"},
        {"command": "post to tiktok", "module": "social", "description": "Post a beat to TikTok"},
        {"command": "show analytics", "module": "analytics", "description": "Get channel analytics"},
        {"command": "assign [beat] to breakfast lane", "module": "lanes", "description": "Assign beats to a lane"},
        {"command": "sync airbit", "module": "airbit", "description": "Compare YouTube vs Airbit catalog"},
        {"command": "help", "module": "agent", "description": "Show this command list"},
    ]
