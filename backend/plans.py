"""Plan catalog, usage accounting and quota enforcement."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from database import get_db

ALL_FORMATS = ["png", "webp", "jpg"]

PLANS: dict[str, dict] = {
    "free": {
        "id": "free",
        "name": "Free",
        "tagline": "Try it out",
        "price_monthly": 0,
        "price_yearly": 0,
        "credits": 5,
        "period": "month",
        "max_dimension": 1024,
        "formats": ALL_FORMATS,
        "highlighted": False,
        "features": [
            "5 removals per month",
            "Exports up to 1024 px",
            "PNG, WebP and JPG",
        ],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "tagline": "For creators",
        "price_monthly": 9,
        "price_yearly": 90,
        "credits": 200,
        "period": "month",
        "max_dimension": 4096,
        "formats": ALL_FORMATS,
        "highlighted": True,
        "features": [
            "200 removals per month",
            "Exports up to 4096 px",
            "PNG, WebP and JPG",
        ],
    },
    "business": {
        "id": "business",
        "name": "Business",
        "tagline": "For teams",
        "price_monthly": 29,
        "price_yearly": 290,
        "credits": 1000,
        "period": "month",
        "max_dimension": 8192,
        "formats": ALL_FORMATS,
        "highlighted": False,
        "features": [
            "1,000 removals per month",
            "Exports up to 8192 px",
            "PNG, WebP and JPG",
            "Commercial usage",
        ],
    },
}

PLAN_ORDER = ["free", "pro", "business"]

GUEST_DAILY_LIMIT = max(0, int(os.getenv("GUEST_DAILY_LIMIT", "2")))
GUEST_MAX_DIMENSION = int(os.getenv("GUEST_MAX_DIMENSION", "1024"))


def plan_for(user: dict | None) -> dict:
    if user is None:
        return {
            "id": "guest",
            "name": "Guest",
            "tagline": "No account needed",
            "price_monthly": 0,
            "price_yearly": 0,
            "credits": GUEST_DAILY_LIMIT,
            "period": "day",
            "max_dimension": GUEST_MAX_DIMENSION,
            "formats": ALL_FORMATS,
            "highlighted": False,
            "features": [],
        }
    return PLANS.get(user.get("plan", "free"), PLANS["free"])


def public_plans() -> list[dict]:
    return [PLANS[key] for key in PLAN_ORDER]


def client_id_for(request: Request) -> str:
    header = (request.headers.get("x-client-id") or "").strip()
    if header and len(header) <= 128 and header.isprintable():
        return header
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _period_start(period: str, now: datetime) -> tuple[str, str]:
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        reset = start + timedelta(days=1)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            reset = start.replace(year=start.year + 1, month=1)
        else:
            reset = start.replace(month=start.month + 1)
    return start.isoformat(), reset.isoformat()


def _count_jobs(since: str, user_id: str | None, client_id: str | None) -> int:
    with get_db() as connection:
        if user_id:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM jobs WHERE user_id = ? AND created_at >= ?",
                (user_id, since),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM jobs WHERE client_id = ? AND created_at >= ?",
                (client_id, since),
            ).fetchone()
    return int(row["total"]) if row else 0


def usage_for(request: Request, user: dict | None) -> dict:
    plan = plan_for(user)
    now = datetime.now(timezone.utc)
    since, resets_at = _period_start(plan["period"], now)

    if user:
        used = _count_jobs(since, user["id"], None)
    else:
        used = _count_jobs(since, None, client_id_for(request))

    limit = int(plan["credits"])
    return {
        "authenticated": user is not None,
        "plan": plan["id"],
        "plan_name": plan["name"],
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "period": plan["period"],
        "resets_at": resets_at,
        "max_dimension": plan["max_dimension"],
        "formats": plan["formats"],
    }


def enforce_quota(request: Request, user: dict | None) -> None:
    usage = usage_for(request, user)
    if usage["remaining"] > 0:
        return
    if user is None:
        raise HTTPException(
            status_code=402,
            detail=(
                "You have used today's free previews. Create a free account "
                "to keep removing backgrounds."
            ),
        )
    raise HTTPException(
        status_code=402,
        detail=(
            "You have used all removals in your plan this month. "
            "Upgrade your plan to continue."
        ),
    )


def resolve_dimension(requested: int | None, user: dict | None) -> int:
    plan = plan_for(user)
    cap = int(plan["max_dimension"])
    if requested is None:
        return cap
    if requested > cap:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{plan['name']} exports are limited to {cap} px. "
                "Upgrade to export at higher resolution."
            ),
        )
    return requested
