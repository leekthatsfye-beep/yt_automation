"""
WebSocket connection manager for real-time progress updates
and in-memory task queue tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Task types that should trigger push notifications on completion
_NOTIFY_TASK_TYPES = {"render", "upload", "store_upload", "social", "sync_links", "fix_titles", "channel_scan", "content_schedule"}


# ── Task tracker ────────────────────────────────────────────────────────

class TaskTracker:
    """In-memory tracker for pipeline tasks (render, upload, social)."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(self, stem: str, task_type: str, title: str) -> str:
        """Register a new task. Returns the task ID."""
        task_id = f"{task_type}_{stem}_{uuid.uuid4().hex[:6]}"
        self._tasks[task_id] = {
            "id": task_id,
            "type": task_type,
            "stem": stem,
            "title": title,
            "status": "running",
            "progress": 0,
            "detail": "",
            "startedAt": time.time(),
            "finishedAt": None,
        }
        return task_id

    def update(self, task_id: str, progress: int, detail: str = "") -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["progress"] = progress
            if detail:
                self._tasks[task_id]["detail"] = detail

    def complete(self, task_id: str) -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task["status"] = "done"
            task["progress"] = 100
            task["finishedAt"] = time.time()
            # Fire push notification for background tasks
            if task.get("type") in _NOTIFY_TASK_TYPES:
                self._fire_push(task)

    def is_complete(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and task.get("status") in ("done", "failed")

    def fail(self, task_id: str, detail: str = "") -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task["status"] = "failed"
            task["detail"] = detail
            task["finishedAt"] = time.time()
            # Fire push notification for background task failures
            if task.get("type") in _NOTIFY_TASK_TYPES:
                self._fire_push(task)

    def _fire_push(self, task: dict[str, Any]) -> None:
        """Fire a push notification for a completed/failed task."""
        from app.backend.services.push_svc import notify_task_complete

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(notify_task_complete(
                task_type=task.get("type", ""),
                title=task.get("title", ""),
                stem=task.get("stem", ""),
                status=task.get("status", ""),
                detail=task.get("detail", ""),
            ))
        except RuntimeError:
            # No running event loop — skip push
            logger.debug("No event loop for push notification")

    def cancel(self, task_id: str) -> bool:
        if task_id in self._tasks and self._tasks[task_id]["status"] == "running":
            self._tasks[task_id]["status"] = "failed"
            self._tasks[task_id]["detail"] = "Cancelled"
            self._tasks[task_id]["finishedAt"] = time.time()
            return True
        return False

    def get_active(self) -> list[dict[str, Any]]:
        """Return running tasks."""
        return [
            t for t in self._tasks.values()
            if t["status"] == "running"
        ]

    def get_completed(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recently completed/failed tasks, newest first."""
        done = [
            t for t in self._tasks.values()
            if t["status"] in ("done", "failed")
        ]
        done.sort(key=lambda t: t.get("finishedAt", 0), reverse=True)
        return done[:limit]

    def prune(self, max_age_hours: int = 24) -> None:
        """Remove completed tasks older than max_age_hours."""
        cutoff = time.time() - max_age_hours * 3600
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t["status"] in ("done", "failed")
            and (t.get("finishedAt") or 0) < cutoff
        ]
        for tid in to_remove:
            del self._tasks[tid]


tracker = TaskTracker()


# ── WebSocket manager ───────────────────────────────────────────────────

class ConnectionManager:
    """Tracks connected WebSocket clients with per-user mapping."""

    def __init__(self) -> None:
        self._active: dict[WebSocket, str] = {}  # ws → username

    async def connect(self, ws: WebSocket, username: str = "anonymous") -> None:
        await ws.accept()
        self._active[ws] = username
        logger.info(
            "WebSocket client connected: %s (%d total)",
            username,
            len(self._active),
        )

    def disconnect(self, ws: WebSocket) -> None:
        username = self._active.pop(ws, "unknown")
        logger.info(
            "WebSocket client disconnected: %s (%d total)",
            username,
            len(self._active),
        )

    async def broadcast(
        self,
        data: dict[str, Any],
        username: str | None = None,
    ) -> None:
        """Send a JSON message to clients.

        If username is given, sends only to that user's connections
        plus any admin connections.  If None, sends to everyone.
        Silently removes dead connections — never crashes the caller.
        """
        try:
            payload = json.dumps(data)
        except Exception:
            return
        stale: list[WebSocket] = []
        for ws, ws_user in list(self._active.items()):
            if username is None or ws_user == username or ws_user == "admin":
                try:
                    await ws.send_text(payload)
                except Exception:
                    stale.append(ws)
        for ws in stale:
            self._active.pop(ws, None)

    async def send_progress(
        self,
        task_id: str,
        phase: str,
        pct: int,
        detail: str = "",
        username: str | None = None,
    ) -> None:
        """Convenience wrapper for progress updates."""
        parts = task_id.rsplit("_", 1)
        stem = parts[0].split("_", 1)[1] if len(parts) == 2 and "_" in parts[0] else ""
        await self.broadcast(
            {
                "type": "progress",
                "taskId": task_id,
                "stem": stem,
                "phase": phase,
                "pct": pct,
                "detail": detail,
            },
            username=username,
        )


manager = ConnectionManager()
