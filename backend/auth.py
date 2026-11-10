"""Email/password authentication with opaque bearer tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from database import get_db

PBKDF2_ITERATIONS = max(50_000, int(os.getenv("PBKDF2_ITERATIONS", "210000")))
SESSION_DAYS = max(1, int(os.getenv("SESSION_DAYS", "30")))
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{b64encode(salt).decode()}${b64encode(digest).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        salt = b64decode(salt_b64)
        expected = b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if len(email) > 254:
        raise HTTPException(status_code=422, detail="Email is too long.")
    return email


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(
            status_code=422, detail="Password must be at least 8 characters."
        )
    if len(password) > 200:
        raise HTTPException(status_code=422, detail="Password is too long.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DAYS)
    with get_db() as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, now.isoformat(), expires.isoformat()),
        )
    return token


def destroy_session(token: str) -> None:
    with get_db() as connection:
        connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),)
        )


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def get_user(request: Request) -> dict | None:
    token = _bearer_token(request)
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as connection:
        row = connection.execute(
            "SELECT users.* FROM sessions "
            "JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (_token_hash(token), now),
        ).fetchone()
    return dict(row) if row else None


def require_user(request: Request) -> dict:
    user = get_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


def get_user_by_id(user_id: str) -> dict | None:
    with get_db() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with get_db() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    return dict(row) if row else None


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "plan": user.get("plan", "free"),
        "plan_interval": user.get("plan_interval", "month"),
        "plan_renews_at": user.get("plan_renews_at"),
        "created_at": user["created_at"],
    }
