"""
/api/render — Video render endpoints.
Wraps render.py subprocess with progress tracking.
Returns immediately; streams real ffmpeg progress via WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException

from app.backend.config import PYTHON, ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import get_beat, safe_stem
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/render", tags=["render"])

# ── ffprobe helper ────────────────────────────────────────────────────────

async def _get_audio_duration(stem: str) -> float:
    """Get audio duration in seconds for a beat stem."""
    for ext in ("mp3", "wav"):
        audio_path = ROOT / "beats" / f"{stem}.{ext}"
        if audio_path.exists():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", str(audio_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    data = json.loads(stdout.decode())
                    return float(data.get("format", {}).get("duration", 0))
            except Exception:
                pass
    return 0.0


# ── ffmpeg progress parser ────────────────────────────────────────────────

_TIME_RE = re.compile(r"time=(\d+):(\d+):([\d.]+)")


def _parse_ffmpeg_time(line: str) -> float | None:
    """Parse ffmpeg stderr 'time=HH:MM:SS.xx' into seconds elapsed."""
    m = _TIME_RE.search(line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


# Stall timeout: kill ffmpeg if no progress for this many seconds
_STALL_TIMEOUT = 180


@router.post("/{stem}")
async def render_beat(stem: str, user: UserContext = Depends(get_current_user)):
    """
    Start rendering a single beat to MP4 video.
    Returns immediately with a taskId — progress streams via WebSocket.
    """
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if beat["rendered"]:
        return {
            "stem": stem,
            "status": "already_rendered",
            "message": f"{stem} is already rendered",
        }

    task_id = tracker.create(stem, "render", beat.get("title", stem))
    await manager.send_progress(task_id, "render", 0, "Starting render...", username=user.username)

    # Build command
    cmd = [
        PYTHON,
        str(ROOT / "render.py"),
        "--only", stem,
    ]

    # Check for media assignment (user-picked clip via MediaPicker)
    meta_path = paths.metadata_dir / f"{stem}.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            clip = meta.get("media", {}).get("clip")
            if clip:
                cmd.extend(["--clip", clip])
                logger.info("Using assigned clip for %s: %s", stem, clip)
        except Exception as e:
            logger.warning("Failed to read media assignment for %s: %s", stem, e)

    # Fire background task — returns immediately to the client
    asyncio.ensure_future(
        _run_render_background(stem, cmd, task_id, user.username, paths.output_dir)
    )

    return {
        "stem": stem,
        "taskId": task_id,
        "status": "started",
        "message": f"Render started for {stem} — track via WebSocket",
    }


async def _run_render_background(
    stem: str,
    cmd: list[str],
    task_id: str,
    username: str,
    output_dir,
) -> None:
    """
    Background coroutine that runs render.py, parses ffmpeg progress from
    stderr, and streams updates via WebSocket. Never blocks the HTTP response.
    """
    audio_duration = await _get_audio_duration(stem)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT),
            limit=1024 * 1024,
        )
    except Exception as e:
        logger.error("Failed to start render for %s: %s", stem, e)
        tracker.fail(task_id, f"Failed to start: {e}")
        await manager.send_progress(task_id, "render", 0, f"Failed to start: {e}", username=username)
        return

    # ── Shared state for concurrent stdout/stderr readers ─────────────
    pct = 0
    last_ws_pct = -1
    encoding_active = False
    last_progress_time = time.time()
    stall_killed = False
    stderr_buf = ""

    async def read_stdout():
        nonlocal pct, last_ws_pct, encoding_active, last_progress_time
        try:
            async for raw in proc.stdout:
                text = raw.decode(errors="replace").strip()
                if not text:
                    continue
                logger.info("render.py: %s", text)

                if "[RENDER]" in text:
                    encoding_active = True
                    pct = 5
                    last_progress_time = time.time()
                    tracker.update(task_id, pct, f"Encoding {stem}...")
                    await manager.send_progress(task_id, "render", pct, f"Encoding {stem}...", username=username)
                    last_ws_pct = pct

                elif "[THUMB]" in text or "[CLIP]" in text:
                    # Thumbnail + clip selection happen BEFORE ffmpeg encoding —
                    # do NOT disable encoding_active here
                    last_progress_time = time.time()

                elif "[DONE]" in text or "[SKIP]" in text:
                    encoding_active = False
                    pct = 100
                    last_progress_time = time.time()
                    tracker.update(task_id, 100, "Complete!")
                    await manager.send_progress(task_id, "render", 100, "Complete!", username=username)
                    last_ws_pct = 100

                elif "[FAIL]" in text:
                    encoding_active = False

        except Exception as e:
            logger.warning("read_stdout error (render continues): %s", e)

    async def read_stderr():
        """Read stderr in raw chunks and split on \\r or \\n.

        ffmpeg prints progress using carriage return (\\r) without newlines,
        so the default async line iterator (which waits for \\n) would buffer
        forever.  Reading raw 4 KB chunks and splitting on both works.
        """
        nonlocal pct, last_ws_pct, last_progress_time, stderr_buf
        partial = ""  # leftover bytes from previous chunk (no \\r or \\n yet)
        try:
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break  # EOF
                text = chunk.decode("utf-8", errors="replace")
                stderr_buf += text
                partial += text

                # Split on any combination of \r and \n
                parts = re.split(r"[\r\n]+", partial)
                partial = parts.pop()  # last piece may be incomplete

                if not encoding_active or audio_duration <= 0:
                    continue

                for line in parts:
                    elapsed = _parse_ffmpeg_time(line)
                    if elapsed is None:
                        continue

                    # Map ffmpeg progress into 5-88% range (encoding phase)
                    raw_pct = min(elapsed / audio_duration * 100, 100.0)
                    mapped_pct = int(5 + raw_pct * 0.83)  # 5% + 0-83% = 5-88%
                    mapped_pct = min(mapped_pct, 88)

                    last_progress_time = time.time()

                    if mapped_pct > pct:
                        pct = mapped_pct

                    # Send WebSocket update every 3% to avoid flooding
                    if pct - last_ws_pct >= 3:
                        last_ws_pct = pct
                        tracker.update(task_id, pct, f"Encoding... {pct}%")
                        await manager.send_progress(
                            task_id, "render", pct,
                            f"Encoding... {pct}%",
                            username=username,
                        )
        except Exception as e:
            logger.warning("read_stderr error (render continues): %s", e)

    async def stall_watchdog():
        nonlocal stall_killed
        while proc.returncode is None:
            await asyncio.sleep(15)
            if proc.returncode is not None:
                break
            if encoding_active and (time.time() - last_progress_time) > _STALL_TIMEOUT:
                logger.warning(
                    "Render stall: %s stuck at %d%% for %ds — killing",
                    stem, pct, _STALL_TIMEOUT,
                )
                stall_killed = True
                try:
                    proc.kill()
                except Exception:
                    pass
                tracker.fail(task_id, f"Stalled at {pct}% — killed after {_STALL_TIMEOUT}s")
                await manager.send_progress(
                    task_id, "render", pct,
                    f"Stalled at {pct}% — killed after {_STALL_TIMEOUT}s",
                    username=username,
                )
                # Clean up partial output
                partial = output_dir / f"{stem}.mp4"
                if partial.exists():
                    try:
                        partial.unlink()
                        logger.info("Removed partial render: %s", partial)
                    except Exception:
                        pass
                break

    # Run all three coroutines concurrently with overall timeout
    overall_timeout = max(20 * 60, int(audio_duration * 4))
    try:
        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr(), stall_watchdog()),
            timeout=overall_timeout,
        )
        await proc.wait()
    except asyncio.TimeoutError:
        logger.error("Render overall timeout (%ds) for %s — killing", overall_timeout, stem)
        try:
            proc.kill()
        except Exception:
            pass
        await proc.wait()
        tracker.fail(task_id, "Render timed out")
        await manager.send_progress(task_id, "render", pct, "Render timed out", username=username)
        return

    if stall_killed:
        return  # Already handled in stall_watchdog

    if proc.returncode != 0:
        err_tail = stderr_buf[-500:] if stderr_buf else "unknown error"
        logger.error("render.py failed for %s (rc=%d): %s", stem, proc.returncode, err_tail)
        tracker.fail(task_id, f"Error: {err_tail[:200]}")
        await manager.send_progress(task_id, "render", pct, f"Error: {err_tail[:200]}", username=username)
        return

    video_path = output_dir / f"{stem}.mp4"
    if not video_path.exists():
        tracker.fail(task_id, f"Output file not found: {stem}.mp4")
        await manager.send_progress(task_id, "render", pct, f"Output not found", username=username)
        return

    tracker.complete(task_id)
    await manager.send_progress(task_id, "render", 100, "Complete!", username=username)
    logger.info("Render complete: %s", stem)
