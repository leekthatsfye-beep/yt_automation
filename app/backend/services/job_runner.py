"""
Background job executor — runs forever inside FastAPI lifespan.

Picks up queued jobs from jobs_queue.json and executes them one at a time
using subprocess calls (render.py, upload.py, seo_metadata.py, etc.).

Jobs continue running even with zero browser clients connected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from app.backend.config import PYTHON, ROOT
from app.backend.services import jobs_svc
from app.backend.services import social_schedule_svc
from app.backend.ws import manager

logger = logging.getLogger(__name__)

# Flag to request graceful shutdown
_shutdown = False

# ffmpeg progress regex
_TIME_RE = re.compile(r"time=(\d+):(\d+):([\d.]+)")

# Stall timeout: kill ffmpeg if no progress for this many seconds
_STALL_TIMEOUT = 180


def request_shutdown() -> None:
    global _shutdown
    _shutdown = True


def _parse_ffmpeg_time(line: str) -> float | None:
    """Parse ffmpeg stderr 'time=HH:MM:SS.xx' into seconds elapsed."""
    m = _TIME_RE.search(line)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


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


async def run_job_loop() -> None:
    """
    Main background loop — runs forever inside FastAPI lifespan.
    Picks next queued job, executes it, marks done/failed, repeats.
    """
    global _shutdown

    # Wait for server startup
    await asyncio.sleep(5)

    # Recover any jobs stuck in "running" from a previous crash
    recovered = jobs_svc.recover_stale_running()
    if recovered:
        logger.info("Job runner recovered %d stale jobs", recovered)

    logger.info("Background job runner started")

    # Launch social schedule checker as a parallel background task
    asyncio.ensure_future(_check_social_schedule())

    while not _shutdown:
        try:
            job = jobs_svc.next_queued()
            if not job:
                await asyncio.sleep(5)
                continue

            job_id = job["id"]
            job_type = job["type"]
            stems = job.get("stems", [])
            params = job.get("params", {})

            logger.info("Starting job %s: %s (%d stems)", job_id, job_type, len(stems))

            # Mark running
            jobs_svc.update_job(
                job_id,
                status="running",
                started_at=jobs_svc._now_iso(),
                progress=5,
                detail=f"Starting {job_type}...",
            )

            # Broadcast to connected clients
            await _broadcast_job_update(job_id)

            try:
                result = await _execute_job(job_id, job_type, stems, params)

                jobs_svc.update_job(
                    job_id,
                    status="done",
                    progress=100,
                    finished_at=jobs_svc._now_iso(),
                    detail="Complete",
                    result=result,
                )
                logger.info("Job %s completed: %s", job_id, job_type)

            except asyncio.CancelledError:
                jobs_svc.update_job(
                    job_id,
                    status="cancelled",
                    finished_at=jobs_svc._now_iso(),
                    detail="Server shutting down",
                )
                logger.info("Job %s cancelled (shutdown)", job_id)
                break

            except Exception as e:
                logger.error("Job %s failed: %s", job_id, e, exc_info=True)
                jobs_svc.update_job(
                    job_id,
                    status="failed",
                    finished_at=jobs_svc._now_iso(),
                    error=str(e)[:500],
                    detail=f"Error: {str(e)[:200]}",
                )

            # Broadcast final state
            await _broadcast_job_update(job_id)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Job runner loop error: %s", e, exc_info=True)
            await asyncio.sleep(10)

    logger.info("Background job runner stopped")


# ── Social schedule checker ────────────────────────────────────────────────

async def _check_social_schedule() -> None:
    """
    Parallel background loop — checks every 30 seconds for due social posts
    and executes them using the existing upload functions.
    """
    import sys

    # Wait a bit for server to be fully ready
    await asyncio.sleep(15)
    logger.info("Social schedule checker started")

    while not _shutdown:
        try:
            due = social_schedule_svc.get_due()
            if due:
                logger.info("Social scheduler found %d due post(s)", len(due))

            for post in due:
                post_id = post["id"]
                stem = post["stem"]
                platforms = post["platforms"]
                caption = post.get("caption", "")
                privacy = post.get("privacy", "public")

                social_schedule_svc.update(post_id, status="running")

                # Broadcast status change
                try:
                    await manager.broadcast({
                        "type": "social_schedule",
                        "post": {**post, "status": "running"},
                    })
                except Exception:
                    pass

                results: dict = {}

                for platform in platforms:
                    try:
                        loop = asyncio.get_event_loop()

                        if platform == "instagram":
                            def _do_ig():
                                sys.path.insert(0, str(ROOT))
                                from social_upload import ig_upload
                                return ig_upload(stem=stem, caption=caption)
                            result = await loop.run_in_executor(None, _do_ig)

                        elif platform == "tiktok":
                            def _do_tt():
                                sys.path.insert(0, str(ROOT))
                                from social_upload import tiktok_upload
                                return tiktok_upload(stem=stem, caption=caption)
                            result = await loop.run_in_executor(None, _do_tt)

                        elif platform == "youtube_shorts":
                            def _do_yt():
                                sys.path.insert(0, str(ROOT))
                                from social_upload import youtube_shorts_upload
                                return youtube_shorts_upload(stem=stem, privacy=privacy)
                            result = await loop.run_in_executor(None, _do_yt)

                        else:
                            result = {"status": "error", "error": f"Unknown platform: {platform}"}

                        results[platform] = result
                        logger.info(
                            "Social schedule %s → %s: %s",
                            post_id, platform, result.get("status", "unknown"),
                        )

                    except Exception as e:
                        logger.error(
                            "Social schedule %s → %s failed: %s",
                            post_id, platform, e, exc_info=True,
                        )
                        results[platform] = {"status": "error", "error": str(e)[:300]}

                # Determine final status
                all_ok = all(
                    r.get("status") == "ok" for r in results.values()
                )
                final_status = "done" if all_ok else "failed"

                social_schedule_svc.update(
                    post_id,
                    status=final_status,
                    results=results,
                )

                logger.info(
                    "Social schedule %s finished: %s (%s)",
                    post_id, final_status, ", ".join(
                        f"{p}={r.get('status', '?')}" for p, r in results.items()
                    ),
                )

                # Broadcast final status to UI
                try:
                    updated_post = {**post, "status": final_status, "results": results}
                    await manager.broadcast({
                        "type": "social_schedule",
                        "post": updated_post,
                    })
                except Exception:
                    pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Social schedule check error: %s", e, exc_info=True)

        await asyncio.sleep(30)

    logger.info("Social schedule checker stopped")


# ── Job executors ──────────────────────────────────────────────────────────

async def _execute_job(
    job_id: str,
    job_type: str,
    stems: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Route to the correct executor based on job type."""

    # Render gets special treatment — needs streaming progress
    if job_type == "render":
        return await _run_render(stems, params, job_id=job_id)

    executors = {
        "seo": _run_seo,
        "render": _run_render,
        "upload": _run_upload,
        "convert": _run_convert,
        "compress": _run_compress,
        "shorts": _run_shorts,
        "tiktok": _run_tiktok,
        "instagram": _run_instagram,
        "schedule": _run_schedule,
        "thumbnail": _run_thumbnail,
        "airbit": _run_airbit,
        "beatstars": _run_beatstars,
    }

    executor = executors.get(job_type)
    if not executor:
        raise ValueError(f"Unknown job type: {job_type}")

    return await executor(stems, params)


async def _run_render(
    stems: list[str],
    params: dict[str, Any],
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Render beats via render.py subprocess with real-time ffmpeg progress.
    Streams encoding progress via WebSocket job updates.
    """
    if stems:
        cmd = [PYTHON, str(ROOT / "render.py"), "--only", ",".join(stems)]
    else:
        cmd = [PYTHON, str(ROOT / "render.py")]

    # Get durations for all stems to calculate per-beat progress
    stem_durations: dict[str, float] = {}
    for stem in (stems or []):
        dur = await _get_audio_duration(stem)
        if dur > 0:
            stem_durations[stem] = dur

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
        limit=1024 * 1024,
    )

    # Shared state
    current_stem: str | None = None
    encoding_active = False
    current_dur = 0.0
    last_progress_time = time.time()
    last_broadcast_pct = -1
    done_count = 0
    skip_count = 0
    total = max(len(stems), 1)
    stall_killed = False
    stderr_buf = ""

    def _overall_pct(beat_pct: float) -> int:
        """Calculate overall job progress across all beats."""
        # Each beat gets an equal slice of 5-95%
        base = 5
        per_beat = 90 / total
        completed_pct = done_count * per_beat
        current_pct = (beat_pct / 100) * per_beat
        return min(95, int(base + completed_pct + current_pct))

    async def _update_job_progress(pct: int, detail: str) -> None:
        """Update job progress on disk and broadcast to UI."""
        nonlocal last_broadcast_pct
        if not job_id or pct - last_broadcast_pct < 2:
            return
        last_broadcast_pct = pct
        jobs_svc.update_job(job_id, progress=pct, detail=detail)
        await _broadcast_job_update(job_id)

    async def read_stdout():
        nonlocal current_stem, encoding_active, current_dur, last_progress_time
        nonlocal done_count, skip_count
        try:
            async for raw in proc.stdout:
                text = raw.decode(errors="replace").strip()
                if not text:
                    continue
                logger.info("render job: %s", text)

                if "[RENDER]" in text:
                    m = re.search(r"\[RENDER\]\s+(\S+)", text)
                    if m:
                        current_stem = m.group(1)
                    encoding_active = True
                    current_dur = stem_durations.get(current_stem or "", 0.0)
                    last_progress_time = time.time()
                    await _update_job_progress(
                        _overall_pct(5),
                        f"Encoding {current_stem}...",
                    )

                elif "[THUMB]" in text or "[CLIP]" in text:
                    # These happen BEFORE ffmpeg encoding — just reset stall timer
                    last_progress_time = time.time()

                elif "[DONE]" in text:
                    encoding_active = False
                    done_count += 1
                    last_progress_time = time.time()
                    await _update_job_progress(
                        _overall_pct(0),
                        f"Rendered {done_count}/{total}",
                    )
                    current_stem = None

                elif "[SKIP]" in text:
                    encoding_active = False
                    skip_count += 1
                    done_count += 1
                    last_progress_time = time.time()
                    await _update_job_progress(
                        _overall_pct(0),
                        f"Skipped (already rendered)",
                    )
                    current_stem = None

                elif "[FAIL]" in text:
                    encoding_active = False
                    done_count += 1
                    current_stem = None

        except Exception as e:
            logger.warning("read_stdout error (job continues): %s", e)

    async def read_stderr():
        """Read stderr in raw chunks — ffmpeg uses \\r not \\n for progress."""
        nonlocal last_progress_time, stderr_buf
        partial = ""
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

                if not encoding_active or current_dur <= 0:
                    continue

                for line in parts:
                    elapsed = _parse_ffmpeg_time(line)
                    if elapsed is None:
                        continue

                    last_progress_time = time.time()

                    # Calculate per-beat encoding percentage
                    beat_pct = min(elapsed / current_dur * 100, 100.0)
                    overall = _overall_pct(beat_pct)

                    await _update_job_progress(
                        overall,
                        f"Encoding {current_stem}... {int(beat_pct)}%",
                    )
        except Exception as e:
            logger.warning("read_stderr error (job continues): %s", e)

    async def stall_watchdog():
        nonlocal stall_killed
        while proc.returncode is None:
            await asyncio.sleep(15)
            if proc.returncode is not None:
                break
            if encoding_active and (time.time() - last_progress_time) > _STALL_TIMEOUT:
                logger.warning(
                    "Render job stall: %s stuck for %ds — killing",
                    current_stem, _STALL_TIMEOUT,
                )
                stall_killed = True
                try:
                    proc.kill()
                except Exception:
                    pass
                # Clean up partial output
                if current_stem:
                    partial = ROOT / "output" / f"{current_stem}.mp4"
                    if partial.exists():
                        try:
                            partial.unlink()
                            logger.info("Removed partial render: %s", partial)
                        except Exception:
                            pass
                break

    # Overall timeout: 20 min per beat minimum 10 min
    overall_timeout = max(total * 20 * 60, 600)

    try:
        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr(), stall_watchdog()),
            timeout=overall_timeout,
        )
        await proc.wait()
    except asyncio.TimeoutError:
        logger.error("Render job overall timeout (%ds) — killing", overall_timeout)
        try:
            proc.kill()
        except Exception:
            pass
        await proc.wait()
        raise RuntimeError(f"Render timed out after {overall_timeout}s")

    if stall_killed:
        raise RuntimeError(
            f"Render stalled on {current_stem} for {_STALL_TIMEOUT}s with no progress"
        )

    if proc.returncode != 0:
        err = stderr_buf[-500:] if stderr_buf else "unknown error"
        raise RuntimeError(f"render.py failed (rc={proc.returncode}): {err}")

    return {
        "rendered": done_count - skip_count,
        "skipped": skip_count,
        "returncode": proc.returncode,
        "error": None,
    }


async def _run_upload(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Upload to YouTube via upload.py."""
    privacy = params.get("privacy", "unlisted")
    cmd = [PYTHON, str(ROOT / "upload.py"), "--privacy", privacy]
    if stems:
        cmd.extend(["--only", ",".join(stems)])

    stdout, stderr, rc = await _run_subprocess(cmd, timeout=600)

    uploaded = stdout.count("Upload complete")
    skipped = stdout.count("[SKIP]")

    return {
        "uploaded": uploaded,
        "skipped": skipped,
        "privacy": privacy,
        "returncode": rc,
        "error": stderr[:500] if rc != 0 else None,
    }


async def _run_seo(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Generate SEO metadata via seo_metadata.py."""
    if stems:
        cmd = [PYTHON, str(ROOT / "seo_metadata.py"), "--only", ",".join(stems), "--force"]
    else:
        cmd = [PYTHON, str(ROOT / "seo_metadata.py")]

    stdout, stderr, rc = await _run_subprocess(cmd)

    generated = stdout.count("Generated")
    existed = stdout.count("exists")

    return {
        "generated": generated,
        "existed": existed,
        "returncode": rc,
        "error": stderr[:500] if rc != 0 else None,
    }


async def _run_convert(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Convert to 9:16 via convert.py."""
    cmd = [PYTHON, str(ROOT / "convert_916.py")]
    if stems:
        cmd.extend(["--only", ",".join(stems)])

    stdout, stderr, rc = await _run_subprocess(cmd)
    return {"returncode": rc, "stdout_tail": stdout[-500:], "error": stderr[:500] if rc != 0 else None}


async def _run_compress(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Compress videos."""
    cmd = [PYTHON, str(ROOT / "compress.py")]
    if stems:
        cmd.extend(["--only", ",".join(stems)])

    stdout, stderr, rc = await _run_subprocess(cmd)
    return {"returncode": rc, "stdout_tail": stdout[-500:], "error": stderr[:500] if rc != 0 else None}


async def _run_shorts(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Upload YouTube Shorts."""
    privacy = params.get("privacy", "unlisted")
    uploaded = 0
    errors = 0
    for stem in stems:
        cmd = [PYTHON, str(ROOT / "upload.py"), "--only", stem, "--privacy", privacy, "--shorts"]
        stdout, stderr, rc = await _run_subprocess(cmd, timeout=300)
        if rc == 0 and ("Upload complete" in stdout or "SUCCESS" in stdout.upper()):
            uploaded += 1
        else:
            errors += 1
    return {"uploaded": uploaded, "errors": errors}


async def _run_tiktok(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Post to TikTok (placeholder — routes through social upload)."""
    return {"message": "TikTok upload not yet automated in background mode", "stems": stems}


async def _run_instagram(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Post to Instagram (placeholder — routes through social upload)."""
    return {"message": "Instagram upload not yet automated in background mode", "stems": stems}


async def _run_schedule(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Schedule uploads at computed time slots."""
    from app.backend.services import schedule_svc

    uploaded = 0
    errors = 0

    for stem in stems:
        try:
            slots = schedule_svc.get_next_slots(n=1)
            if not slots:
                break
            slot_time = slots[0]["slot"]

            cmd = [
                PYTHON, str(ROOT / "upload.py"),
                "--only", stem,
                "--schedule-at", slot_time,
            ]
            stdout, stderr, rc = await _run_subprocess(cmd, timeout=300)

            if rc == 0:
                schedule_svc.remove_from_queue(stem)
                uploaded += 1
            else:
                errors += 1
        except Exception as e:
            logger.error("Schedule job failed for %s: %s", stem, e)
            errors += 1

    return {"scheduled": uploaded, "errors": errors}


async def _run_thumbnail(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Generate AI thumbnails."""
    generated = 0
    errors = 0
    for stem in stems:
        cmd = [PYTHON, str(ROOT / "thumbnail_ai.py"), "--stem", stem]
        stdout, stderr, rc = await _run_subprocess(cmd, timeout=120)
        if rc == 0:
            generated += 1
        else:
            errors += 1
    return {"generated": generated, "errors": errors}


async def _run_airbit(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Upload to Airbit."""
    return {"message": "Airbit upload runs via store sync", "stems": stems}


async def _run_beatstars(stems: list[str], params: dict[str, Any]) -> dict[str, Any]:
    """Upload to BeatStars."""
    return {"message": "BeatStars upload runs via store sync", "stems": stems}


# ── Subprocess helper ──────────────────────────────────────────────────────

async def _run_subprocess(
    cmd: list[str],
    timeout: int = 300,
) -> tuple[str, str, int]:
    """
    Run a subprocess asynchronously with streaming progress updates.
    Returns (stdout, stderr, returncode).
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
    )

    stdout_lines: list[str] = []

    # Stream stdout for logging
    while True:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return "".join(stdout_lines), "Timed out", -1

        if not line:
            break
        text = line.decode(errors="replace").strip()
        if text:
            stdout_lines.append(text + "\n")
            logger.info("job: %s", text)

    await proc.wait()
    stderr = (await proc.stderr.read()).decode(errors="replace")

    return "".join(stdout_lines), stderr, proc.returncode


# ── WebSocket broadcast ───────────────────────────────────────────────────

async def _broadcast_job_update(job_id: str) -> None:
    """Send job state update to connected WebSocket clients."""
    job = jobs_svc.get_job(job_id)
    if job:
        try:
            await manager.broadcast({
                "type": "job_update",
                "job": {
                    "id": job["id"],
                    "type": job["type"],
                    "status": job["status"],
                    "progress": job.get("progress", 0),
                    "detail": job.get("detail", ""),
                    "label": job.get("label", ""),
                },
            })
        except Exception:
            pass  # No clients connected, that's fine
