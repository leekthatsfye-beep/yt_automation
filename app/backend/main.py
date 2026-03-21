"""
FY3 Automation Center — FastAPI backend.

Run:
    cd /Users/fyefye/yt_automation
    .venv/bin/python -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from app.backend.config import BEATS_DIR, OUTPUT_DIR, METADATA_DIR, LISTINGS_DIR, UPLOADS_LOG, ROOT
from app.backend.ws import manager, tracker
from app.backend.auth import decode_token, ensure_admin_exists
from app.backend.services import health_svc
from app.backend.services import job_runner

from app.backend.routers import beats, system, studio, render, youtube, social, seo, analytics, schedule, stores, health, compress, media, convert, lanes, trends, revival, integrity, agent, airbit_sync, brand, jobs, channel_manager, content_schedule, copyright, dj, organizer, arrangement
from app.backend.routers import auth_router, files

# ── logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("fy3")


# ── lifespan ─────────────────────────────────────────────────────────────

HEALTH_SCAN_INTERVAL = 3600   # 60 minutes
CHANNEL_SCAN_INTERVAL = 86400  # 24 hours (once per day — quota friendly)


async def _daily_channel_scan():
    """Run youtube_manager.py scan once per day at low API cost.

    Quota budget:
      - channels.list = 1 unit
      - playlistItems.list = ~2 units (100 videos)
      - videos.list = ~2 units (100 videos, 50/page)
      Total scan ≈ 5 units out of 10,000 daily quota.
      Auto-fix is OFF for the daily cron — scan only, save report.
    """
    from app.backend.config import PYTHON
    await asyncio.sleep(120)  # Let startup and first health scan finish
    while True:
        try:
            logger.info("Starting daily YouTube channel scan (scan-only, no fixes)")
            proc = await asyncio.create_subprocess_exec(
                PYTHON,
                str(ROOT / "youtube_manager.py"),
                # NO --fix flag: scan-only costs ~5 API units
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT),
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Daily channel scan complete")
                # Broadcast to connected clients
                import json as _json
                report_path = ROOT / "channel_health_report.json"
                if report_path.exists():
                    try:
                        report = _json.loads(report_path.read_text())
                        await manager.broadcast({
                            "type": "channel_scan_complete",
                            "health_score": report.get("channel_health_score", 0),
                            "health_level": report.get("health_level", ""),
                            "total_issues": report.get("issues", {}).get("total", 0),
                            "fixes_applied": 0,
                        })
                    except Exception:
                        pass
            else:
                err = stderr.decode(errors="replace")[:500]
                logger.error("Daily channel scan failed: %s", err)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Daily channel scan error: %s", e)
        await asyncio.sleep(CHANNEL_SCAN_INTERVAL)


async def _periodic_health_scan():
    """Run a health scan every HEALTH_SCAN_INTERVAL seconds."""
    await asyncio.sleep(30)  # Wait for startup to finish
    while True:
        try:
            logger.info("Starting periodic health scan")
            result = await health_svc.run_full_scan(
                beats_dir=BEATS_DIR,
                metadata_dir=METADATA_DIR,
                output_dir=OUTPUT_DIR,
                listings_dir=LISTINGS_DIR,
                uploads_log_path=UPLOADS_LOG,
            )
            logger.info(
                "Health scan complete: score=%d, issues=%d, fixes=%d",
                result["health_score"],
                result["total_issues"],
                result["auto_fixes_applied"],
            )
            # Broadcast to all connected clients
            await manager.broadcast({
                "type": "health_scan_complete",
                "health_score": result["health_score"],
                "health_level": result["health_level"],
                "total_issues": result["total_issues"],
                "auto_fixes_applied": result["auto_fixes_applied"],
                "last_scan_at": result["last_scan_at"],
            })
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Periodic health scan error: %s", e)
        await asyncio.sleep(HEALTH_SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_admin_exists()
    logger.info("FY3 Automation Center API running")
    scan_task = asyncio.ensure_future(_periodic_health_scan())
    channel_task = asyncio.ensure_future(_daily_channel_scan())
    jobs_task = asyncio.ensure_future(job_runner.run_job_loop())
    logger.info("Background job runner started")
    logger.info("Daily YouTube channel scan scheduled (every 24h, ~5 API units)")
    yield
    scan_task.cancel()
    channel_task.cancel()
    job_runner.request_shutdown()
    jobs_task.cancel()
    logger.info("FY3 Automation Center API shutting down")


# ── app ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FY3 Automation Center",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── routers ──────────────────────────────────────────────────────────────

app.include_router(auth_router.router)
app.include_router(beats.router)
app.include_router(system.router)
app.include_router(studio.router)
app.include_router(render.router)
app.include_router(youtube.router)
app.include_router(social.router)
app.include_router(seo.router)
app.include_router(analytics.router)
app.include_router(schedule.router)
app.include_router(stores.router)
app.include_router(health.router)
app.include_router(compress.router)
app.include_router(media.router)
app.include_router(convert.router)
app.include_router(lanes.router)
app.include_router(trends.router)
app.include_router(revival.router)
app.include_router(integrity.router)
app.include_router(agent.router)
app.include_router(airbit_sync.router)
app.include_router(brand.router)
app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(channel_manager.router)
app.include_router(content_schedule.router)
app.include_router(copyright.router)
app.include_router(dj.router)
app.include_router(organizer.router)
app.include_router(arrangement.router)

# ── ensure directories exist ─────────────────────────────────────────────

OUTPUT_DIR.mkdir(exist_ok=True)
BEATS_DIR.mkdir(exist_ok=True)

from app.backend.config import STUDIO_DIR

STUDIO_DIR.mkdir(exist_ok=True)


# ── task status API ──────────────────────────────────────────────────────

from app.backend.deps import get_current_user, UserContext
from fastapi import Depends


@app.get("/api/tasks/active")
async def get_active_tasks(user: UserContext = Depends(get_current_user)):
    """Return all currently running tasks."""
    return tracker.get_active()


@app.get("/api/tasks/recent")
async def get_recent_tasks(user: UserContext = Depends(get_current_user)):
    """Return recently completed tasks (last 20)."""
    return tracker.get_completed(limit=20)


# ── websocket (authenticated) ────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str | None = Query(None)):
    # Validate JWT token
    if not token:
        await ws.close(code=4001)
        return
    payload = decode_token(token)
    if not payload:
        await ws.close(code=4001)
        return

    username = payload["sub"]
    await manager.connect(ws, username=username)

    # Send any active tasks to the newly connected client so they can
    # restore progress bars after navigating away and coming back.
    active = tracker.get_active()
    if active:
        for task in active:
            try:
                await ws.send_text(json.dumps({
                    "type": "progress",
                    "taskId": task["id"],
                    "stem": task.get("stem", ""),
                    "phase": task.get("type", ""),
                    "pct": task.get("progress", 0),
                    "detail": task.get("detail", ""),
                }))
            except Exception:
                pass

    async def _send_pings():
        """Send keepalive pings every 25s to prevent proxy/network timeouts."""
        try:
            while True:
                await asyncio.sleep(25)
                try:
                    await ws.send_text('{"type":"ping"}')
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_send_pings())
    try:
        while True:
            data = await ws.receive_text()
            # Don't echo pings back
            if data.strip() not in ('{"type":"ping"}', '{"type":"pong"}'):
                await ws.send_text(data)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.warning("WebSocket error for %s: %s", username, e)
        manager.disconnect(ws)
    finally:
        ping_task.cancel()
