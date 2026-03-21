"""
FY3 Authentication — JWT tokens, bcrypt password hashing, user CRUD.

Users are stored in users.json at project root.
JWT secret is auto-generated and stored in .jwt_secret.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

import bcrypt
from jose import jwt, JWTError

from app.backend.config import ROOT

logger = logging.getLogger(__name__)

# ── paths ────────────────────────────────────────────────────────────────

USERS_FILE = ROOT / "users.json"
JWT_SECRET_FILE = ROOT / ".jwt_secret"
PRODUCERS_DIR = ROOT / "producers"

# ── constants ────────────────────────────────────────────────────────────

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72  # 3 days


def _get_secret() -> str:
    """Load or auto-generate JWT signing secret."""
    if JWT_SECRET_FILE.exists():
        return JWT_SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    JWT_SECRET_FILE.write_text(secret)
    logger.info("Generated new JWT secret at %s", JWT_SECRET_FILE)
    return secret


SECRET_KEY = _get_secret()


# ── user storage ────────────────────────────────────────────────────────

def _load_users() -> dict[str, Any]:
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            logger.warning("Could not parse users.json, returning empty")
    return {}


def _save_users(users: dict[str, Any]) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2))


# ── password helpers ────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── authentication ──────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """Verify credentials. Returns user info dict or None."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {
        "username": username,
        "role": user["role"],
        "display_name": user.get("display_name", username),
    }


# ── JWT tokens ──────────────────────────────────────────────────────────

def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": time.time() + TOKEN_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns payload dict or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except JWTError:
        return None


# ── user CRUD ───────────────────────────────────────────────────────────

def create_user(
    username: str,
    password: str,
    role: str = "producer",
    display_name: str = "",
) -> dict[str, Any]:
    """Create a new user. Creates producer directories if role is producer."""
    users = _load_users()
    if username in users:
        raise ValueError(f"User '{username}' already exists")

    users[username] = {
        "password_hash": hash_password(password),
        "role": role,
        "display_name": display_name or username,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_users(users)

    # Create producer workspace directories
    if role == "producer":
        base = PRODUCERS_DIR / username
        for d in ["beats", "metadata", "output", "studio"]:
            (base / d).mkdir(parents=True, exist_ok=True)
        logger.info("Created producer workspace: %s", base)

    logger.info("Created user: %s (role=%s)", username, role)
    return {
        "username": username,
        "role": role,
        "display_name": display_name or username,
    }


def delete_user(username: str) -> bool:
    """Delete a user. Does NOT delete their data directories."""
    users = _load_users()
    if username not in users:
        return False
    if users[username]["role"] == "admin":
        raise ValueError("Cannot delete admin account")
    del users[username]
    _save_users(users)
    logger.info("Deleted user: %s", username)
    return True


def list_users() -> list[dict[str, Any]]:
    """Return all users (without password hashes)."""
    users = _load_users()
    return [
        {
            "username": uname,
            "role": data["role"],
            "display_name": data.get("display_name", uname),
            "created_at": data.get("created_at", ""),
        }
        for uname, data in users.items()
    ]


def change_password(username: str, new_password: str) -> bool:
    """Change a user's password."""
    users = _load_users()
    if username not in users:
        return False
    users[username]["password_hash"] = hash_password(new_password)
    _save_users(users)
    logger.info("Changed password for user: %s", username)
    return True


# ── first-run setup ─────────────────────────────────────────────────────

def ensure_admin_exists() -> None:
    """Create admin account on first run if users.json is empty or missing."""
    import os

    users = _load_users()
    # Check if any admin exists
    has_admin = any(u.get("role") == "admin" for u in users.values())
    if has_admin:
        return

    password = os.environ.get("FY3_ADMIN_PASSWORD")
    if not password:
        password = secrets.token_urlsafe(12)
        logger.info("=" * 60)
        logger.info("  FY3 ADMIN ACCOUNT CREATED")
        logger.info("  Username: admin")
        logger.info("  Password: %s", password)
        logger.info("  (Set FY3_ADMIN_PASSWORD env var to choose your own)")
        logger.info("=" * 60)

    create_user("admin", password, role="admin", display_name="FY3 Admin")
