"""
Web Push notification service.

Sends push notifications to subscribed browsers/devices when
background tasks complete (renders, uploads, store sync, etc).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.backend.config import APP_SETTINGS

logger = logging.getLogger(__name__)


def _load_settings() -> dict:
    if APP_SETTINGS.exists():
        return json.loads(APP_SETTINGS.read_text())
    return {}


def _save_settings(data: dict) -> None:
    APP_SETTINGS.write_text(json.dumps(data, indent=2))


def get_vapid_public_key() -> str:
    """Return the VAPID public key for the frontend."""
    settings = _load_settings()
    return settings.get("vapid", {}).get("public_key", "")


def get_subscriptions() -> list[dict]:
    """Return all stored push subscriptions."""
    settings = _load_settings()
    return settings.get("push_subscriptions", [])


def add_subscription(subscription: dict) -> bool:
    """Store a new push subscription. Returns True if new."""
    settings = _load_settings()
    subs = settings.get("push_subscriptions", [])

    # Dedupe by endpoint
    endpoint = subscription.get("endpoint", "")
    for existing in subs:
        if existing.get("endpoint") == endpoint:
            # Update keys if changed
            existing.update(subscription)
            _save_settings(settings)
            return False

    subs.append(subscription)
    settings["push_subscriptions"] = subs
    _save_settings(settings)
    logger.info("New push subscription added (%d total)", len(subs))
    return True


def remove_subscription(endpoint: str) -> bool:
    """Remove a subscription by endpoint."""
    settings = _load_settings()
    subs = settings.get("push_subscriptions", [])
    before = len(subs)
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    settings["push_subscriptions"] = subs
    _save_settings(settings)
    return len(subs) < before


async def send_notification(
    title: str,
    body: str,
    tag: str = "fy3",
    url: str = "/",
    icon: str = "/icon-192.png",
) -> int:
    """
    Send a push notification to all subscribed devices.
    Returns number of successful deliveries.
    """
    from pywebpush import webpush, WebPushException

    settings = _load_settings()
    vapid = settings.get("vapid", {})
    subs = settings.get("push_subscriptions", [])

    if not vapid.get("private_key") or not subs:
        return 0

    vapid_claims = {
        "sub": vapid.get("subject", "mailto:noreply@fy3.app"),
    }

    payload = json.dumps({
        "title": title,
        "body": body,
        "tag": tag,
        "url": url,
        "icon": icon,
    })

    sent = 0
    stale_endpoints: list[str] = []

    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=vapid["private_key"],
                vapid_claims=vapid_claims,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e, "response", None)
            status_code = getattr(status, "status_code", 0) if status else 0
            if status_code in (404, 410):
                # Subscription expired or invalid — mark for removal
                stale_endpoints.append(sub.get("endpoint", ""))
                logger.info("Push subscription expired, removing")
            else:
                logger.warning("Push notification failed: %s", e)
        except Exception as e:
            logger.warning("Push notification error: %s", e)

    # Clean up stale subscriptions
    if stale_endpoints:
        settings = _load_settings()
        subs = settings.get("push_subscriptions", [])
        subs = [s for s in subs if s.get("endpoint") not in stale_endpoints]
        settings["push_subscriptions"] = subs
        _save_settings(settings)

    return sent


async def notify_task_complete(
    task_type: str,
    title: str,
    stem: str,
    status: str,
    detail: str = "",
) -> None:
    """
    Send a push notification when a background task completes.
    Groups by task type for cleaner notifications.
    """
    type_labels = {
        "render": "Render",
        "upload": "YouTube Upload",
        "store_upload": "Store Upload",
        "social": "Social Post",
    }
    label = type_labels.get(task_type, task_type)

    if status == "done":
        notif_title = f"{label} Complete"
        notif_body = title or stem
        tag = f"fy3-{task_type}-done"
    else:
        notif_title = f"{label} Failed"
        notif_body = detail or title or stem
        tag = f"fy3-{task_type}-fail"

    url_map = {
        "render": "/beats",
        "upload": "/beats",
        "store_upload": "/stores",
        "social": "/social",
    }

    await send_notification(
        title=notif_title,
        body=notif_body,
        tag=tag,
        url=url_map.get(task_type, "/"),
    )
