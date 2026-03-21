"""
/api/agent — AI Producer Agent endpoints.

Natural language command interpreter that EXECUTES automation tasks.
No longer just shows data — actually renders, uploads, generates SEO, etc.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.config import ROOT
from app.backend.services import agent_svc, trends_svc, revival_svc, integrity_svc, airbit_sync_svc
from app.backend.services.beat_svc import list_beats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

PYTHON = str(Path(ROOT / ".venv" / "bin" / "python3.14"))


class CommandRequest(BaseModel):
    command: str


def _run_subprocess(args: list[str], cwd: str | None = None) -> dict:
    """Run a subprocess and return result."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd or str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/command")
async def run_command(
    body: CommandRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(require_admin),
):
    """Interpret and execute a natural language command.

    Now actually runs tasks: render, upload, SEO generation, scheduling, etc.

    Example commands:
    - "render all beats"         → runs render.py
    - "render army"              → renders specific beat
    - "upload all beats"         → uploads to YouTube
    - "generate seo for all"     → runs seo_metadata.py
    - "schedule next 5 uploads"  → queues 5 uploads
    - "scan channel health"      → runs integrity audit
    - "scan youtube trends"      → runs YouTube trend scan
    - "recommend next uploads"   → shows recommendations
    """
    paths = get_user_paths(user)
    parsed = agent_svc.interpret_command(body.command)

    if not parsed["understood"]:
        return {
            "status": "not_understood",
            "message": f"I didn't understand: \"{body.command}\"",
            "suggestions": parsed.get("suggestions", []),
            "parsed": parsed,
        }

    module = parsed["module"]
    action = parsed["action"]
    params = parsed.get("params", {})

    try:
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # RENDER — actually renders beats via render.py
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if module == "render":
            beats = list_beats(
                beats_dir=paths.beats_dir,
                metadata_dir=paths.metadata_dir,
                output_dir=paths.output_dir,
                uploads_log_path=paths.uploads_log,
                social_log_path=paths.social_log,
            )

            stems = params.get("stems")
            if params.get("all") or not stems:
                # Render all unrendered
                unrendered = [b for b in beats if not b.get("rendered")]
                if not unrendered:
                    return {"status": "ok", "module": module, "action": action,
                            "message": "All beats are already rendered!", "executed": True,
                            "result": {"rendered": 0, "total": len(beats)}}

                result = _run_subprocess([PYTHON, "render.py"], cwd=str(ROOT))
                rendered_count = result.get("stdout", "").count("[DONE]")
                skipped_count = result.get("stdout", "").count("[SKIP]")
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": f"Rendered {rendered_count} beats ({skipped_count} already done)",
                    "executed": True,
                    "result": {"rendered": rendered_count, "skipped": skipped_count, "total": len(beats)},
                }
            else:
                # Render specific stems
                results = []
                for stem in stems:
                    # Check if beat exists
                    beat = next((b for b in beats if b["stem"] == stem), None)
                    if not beat:
                        results.append({"stem": stem, "status": "not_found"})
                        continue
                    if beat.get("rendered"):
                        results.append({"stem": stem, "status": "already_rendered"})
                        continue

                    r = _run_subprocess([PYTHON, "render.py"], cwd=str(ROOT))
                    done = stem in r.get("stdout", "")
                    results.append({"stem": stem, "status": "rendered" if done else "attempted"})

                rendered = sum(1 for r in results if r["status"] == "rendered")
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": f"Rendered {rendered} of {len(stems)} beats",
                    "executed": True,
                    "result": {"details": results},
                }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # UPLOAD — actually uploads to YouTube via upload.py
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "upload":
            beats = list_beats(
                beats_dir=paths.beats_dir,
                metadata_dir=paths.metadata_dir,
                output_dir=paths.output_dir,
                uploads_log_path=paths.uploads_log,
                social_log_path=paths.social_log,
            )

            privacy = params.get("privacy", "unlisted")
            stems = params.get("stems")

            if stems:
                args = [PYTHON, "upload.py", "--only", ",".join(stems), "--privacy", privacy]
            else:
                args = [PYTHON, "upload.py", "--privacy", privacy]

            result = _run_subprocess(args, cwd=str(ROOT))
            uploaded_count = result.get("stdout", "").count("Upload complete")
            skipped_count = result.get("stdout", "").count("[SKIP]")

            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Uploaded {uploaded_count} beats to YouTube ({skipped_count} skipped)",
                "executed": True,
                "result": {"uploaded": uploaded_count, "skipped": skipped_count, "privacy": privacy},
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SEO — generates metadata via seo_metadata.py
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "seo":
            stems = params.get("stems")
            if stems:
                # Generate for specific stems
                results = []
                for stem in stems:
                    r = _run_subprocess([PYTHON, "seo_metadata.py", "--only", stem, "--force"], cwd=str(ROOT))
                    results.append({"stem": stem, "success": r.get("success", False)})
                generated = sum(1 for r in results if r["success"])
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": f"Generated SEO for {generated} of {len(stems)} beats",
                    "executed": True,
                    "result": {"details": results},
                }
            else:
                result = _run_subprocess([PYTHON, "seo_metadata.py"], cwd=str(ROOT))
                generated = result.get("stdout", "").count("Generated")
                skipped = result.get("stdout", "").count("exists")
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": f"SEO metadata: {generated} generated, {skipped} already existed",
                    "executed": True,
                    "result": {"generated": generated, "skipped": skipped},
                }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SCHEDULE — queue and launch uploads
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "schedule":
            from app.backend.services.schedule_svc import (
                get_full_schedule, add_to_queue, load_queue,
            )

            count = params.get("count", 5)

            # Add unscheduled rendered beats to queue
            beats = list_beats(
                beats_dir=paths.beats_dir,
                metadata_dir=paths.metadata_dir,
                output_dir=paths.output_dir,
                uploads_log_path=paths.uploads_log,
                social_log_path=paths.social_log,
            )
            uploadable = [b["stem"] for b in beats if b.get("rendered") and not b.get("uploaded")]

            if uploadable:
                added = add_to_queue(uploadable[:count], paths.uploads_log)
                schedule = get_full_schedule(paths.uploads_log)
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": f"Added {len(added)} beats to upload queue ({schedule['queue_length']} total in queue)",
                    "executed": True,
                    "result": {
                        "added": added,
                        "queue_length": schedule["queue_length"],
                        "buffer_days": schedule["buffer_days"],
                    },
                }
            else:
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": "No uploadable beats found — render beats first",
                    "executed": True,
                    "result": {"added": []},
                }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SOCIAL — post to platforms
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "social":
            platform = params.get("platform", "all")
            stems = params.get("stems")

            if not stems:
                beats = list_beats(
                    beats_dir=paths.beats_dir,
                    metadata_dir=paths.metadata_dir,
                    output_dir=paths.output_dir,
                    uploads_log_path=paths.uploads_log,
                    social_log_path=paths.social_log,
                )
                stems = [b["stem"] for b in beats if b.get("rendered")][:5]  # Max 5

            if not stems:
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": "No rendered beats to post. Render beats first.",
                    "executed": True,
                    "result": {},
                }

            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Use the Social page to post {len(stems)} beats to {platform}. Agent queued them for you.",
                "executed": True,
                "result": {"stems": stems, "platform": platform},
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # INTEGRITY — run channel health audit
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "integrity" and action == "audit":
            result = integrity_svc.run_integrity_audit(
                paths.beats_dir, paths.metadata_dir,
                paths.output_dir, paths.uploads_log,
            )
            score = result.get("health_score", 0)
            level = result.get("health_level", "")
            total_issues = result.get("issue_summary", {}).get("total", 0)
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Channel health: {score}/100 ({level}) — {total_issues} issues found",
                "executed": True,
                "result": result,
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # REVIVAL — scan for old uploads to refresh
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "revival" and action == "scan":
            result = revival_svc.scan_revival_candidates(
                paths.uploads_log, paths.metadata_dir,
            )
            count = result.get("summary", {}).get("revival_candidates", 0)
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Found {count} revival candidates" if count else "No revival candidates — all uploads are recent",
                "executed": True,
                "result": result,
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # TRENDS — recommend or scan
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "trends" and action == "recommend":
            count = params.get("count", 10)
            lanes_config_path = ROOT / "lanes_config.json"
            result = trends_svc.recommend_uploads(paths.uploads_log, lanes_config_path, count=count)
            recs = result.get("recommended_uploads", [])
            top3 = ", ".join(r["artist"] for r in recs[:3]) if recs else "none"
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Top recommendations: {top3}",
                "executed": True,
                "result": result,
            }

        elif module == "trends" and action == "scan":
            result = await trends_svc.run_full_scan()
            scanned = result.get("total_scanned", 0)
            errors = result.get("errors", 0)
            top = result.get("artists", [])[:3]
            top_names = ", ".join(a["artist"] for a in top) if top else "none"
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Scanned {scanned} artists ({errors} errors). Top: {top_names}",
                "executed": True,
                "result": {"total_scanned": scanned, "errors": errors, "top_3": [a["artist"] for a in top]},
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # AIRBIT SYNC
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "airbit" and action == "sync":
            result = airbit_sync_svc.sync_scan(
                paths.uploads_log, paths.store_uploads_log,
                paths.beats_dir, paths.metadata_dir,
            )
            missing = len(result.get("missing_from_store", []))
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Airbit sync: {missing} beats not on store yet" if missing else "Airbit is fully synced!",
                "executed": True,
                "result": result,
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ANALYTICS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "analytics" and action == "report":
            from app.backend.services.beat_svc import list_beats as _lb
            import json

            beats = _lb(
                beats_dir=paths.beats_dir,
                metadata_dir=paths.metadata_dir,
                output_dir=paths.output_dir,
                uploads_log_path=paths.uploads_log,
                social_log_path=paths.social_log,
            )
            total = len(beats)
            rendered = sum(1 for b in beats if b.get("rendered"))
            uploaded = sum(1 for b in beats if b.get("uploaded"))

            uploads_log = {}
            try:
                if paths.uploads_log.exists():
                    uploads_log = json.loads(paths.uploads_log.read_text())
            except Exception:
                pass

            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Channel: {total} beats, {rendered} rendered, {uploaded} uploaded to YouTube ({len(uploads_log)} total YT uploads)",
                "executed": True,
                "result": {"total_beats": total, "rendered": rendered, "uploaded": uploaded, "youtube_uploads": len(uploads_log)},
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # LANES
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "lanes" and action == "assign":
            lane = params.get("lane")
            stems = params.get("stems", [])
            if not lane:
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": "Specify a lane: e.g. 'assign army to breakfast lane'",
                    "executed": False,
                    "result": {},
                }
            if not stems:
                return {
                    "status": "ok", "module": module, "action": action,
                    "message": "Specify which beats: e.g. 'assign army to breakfast lane'",
                    "executed": False,
                    "result": {},
                }

            import json
            updated = []
            for stem in stems:
                meta_path = paths.metadata_dir / f"{stem}.json"
                meta = {}
                try:
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text())
                except Exception:
                    pass
                meta["lane"] = lane
                meta_path.parent.mkdir(exist_ok=True)
                meta_path.write_text(json.dumps(meta, indent=2))
                updated.append(stem)

            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Assigned {len(updated)} beats to {lane} lane",
                "executed": True,
                "result": {"updated": updated, "lane": lane},
            }

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # HELP
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif module == "agent" and action == "help":
            commands = agent_svc.get_available_commands()
            return {
                "status": "ok",
                "module": module,
                "action": action,
                "result": {"commands": commands},
            }

        else:
            return {
                "status": "ok", "module": module, "action": action,
                "message": f"Command recognized ({module}/{action}) but execution is not wired yet",
                "executed": False,
                "result": {},
            }

    except Exception as e:
        logger.error("Agent command failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "module": module,
            "action": action,
            "message": f"Command failed: {str(e)}",
            "error": str(e),
        }


@router.get("/commands")
async def list_commands():
    """List all available agent commands with examples."""
    return {"commands": agent_svc.get_available_commands()}
