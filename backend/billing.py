"""Subscription billing with Stripe and a safe local development mode."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException, Request

from database import get_db
from plans import PLANS

STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
DEV_BILLING = os.getenv("CUTOUT_DEV_BILLING", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}

PRICE_IDS: dict[tuple[str, str], str] = {
    ("pro", "month"): os.getenv("STRIPE_PRICE_PRO_MONTHLY", "").strip(),
    ("pro", "year"): os.getenv("STRIPE_PRICE_PRO_YEARLY", "").strip(),
    ("business", "month"): os.getenv("STRIPE_PRICE_BUSINESS_MONTHLY", "").strip(),
    ("business", "year"): os.getenv("STRIPE_PRICE_BUSINESS_YEARLY", "").strip(),
}


def billing_mode() -> str:
    return "stripe" if STRIPE_SECRET and any(PRICE_IDS.values()) else "dev"


def _renewal_date(interval: str) -> str:
    now = datetime.now(timezone.utc)
    days = 365 if interval == "year" else 30
    return (now + timedelta(days=days)).isoformat()


def set_plan(user_id: str, plan: str, interval: str = "month") -> None:
    with get_db() as connection:
        connection.execute(
            "UPDATE users SET plan = ?, plan_interval = ?, plan_renews_at = ? "
            "WHERE id = ?",
            (plan, interval, _renewal_date(interval) if plan != "free" else None, user_id),
        )


def downgrade_to_free(user_id: str) -> None:
    with get_db() as connection:
        connection.execute(
            "UPDATE users SET plan = 'free', plan_interval = 'month', "
            "plan_renews_at = NULL, stripe_subscription_id = NULL WHERE id = ?",
            (user_id,),
        )


def _price_for(plan: str, interval: str) -> str:
    return PRICE_IDS.get((plan, interval), "")


async def _stripe_request(method: str, path: str, data: dict | None = None) -> dict:
    if not STRIPE_SECRET:
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(
            method,
            f"https://api.stripe.com/v1/{path}",
            data=data or {},
            headers={"Authorization": f"Bearer {STRIPE_SECRET}"},
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail="The payment provider could not complete the request.",
        )
    return response.json()


async def _ensure_customer(user: dict) -> str:
    customer_id = user.get("stripe_customer_id")
    if customer_id:
        return customer_id
    customer = await _stripe_request(
        "POST",
        "customers",
        {"email": user["email"], "metadata[user_id]": user["id"]},
    )
    with get_db() as connection:
        connection.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (customer["id"], user["id"]),
        )
    return customer["id"]


async def create_checkout(user: dict, plan: str, interval: str) -> dict:
    if plan not in PLANS or plan == "free":
        raise HTTPException(status_code=422, detail="Choose a paid plan.")
    if interval not in {"month", "year"}:
        raise HTTPException(status_code=422, detail="Choose monthly or yearly billing.")

    price = _price_for(plan, interval)
    if STRIPE_SECRET:
        if not price:
            raise HTTPException(
                status_code=503,
                detail=f"Stripe price is not configured for {plan} ({interval}).",
            )
        customer_id = await _ensure_customer(user)
        session = await _stripe_request(
            "POST",
            "checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "line_items[0][price]": price,
                "line_items[0][quantity]": "1",
                "allow_promotion_codes": "true",
                "success_url": f"{FRONTEND_URL}/#account?checkout=success",
                "cancel_url": f"{FRONTEND_URL}/#pricing",
                "client_reference_id": user["id"],
                "metadata[user_id]": user["id"],
                "metadata[plan]": plan,
                "metadata[interval]": interval,
                "subscription_data[metadata][user_id]": user["id"],
                "subscription_data[metadata][plan]": plan,
                "subscription_data[metadata][interval]": interval,
            },
        )
        return {"mode": "stripe", "url": session["url"]}

    if DEV_BILLING:
        set_plan(user["id"], plan, interval)
        return {"mode": "dev", "upgraded": True}

    raise HTTPException(status_code=503, detail="Billing is not configured.")


async def create_portal(user: dict) -> dict:
    if STRIPE_SECRET:
        customer_id = user.get("stripe_customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=503,
                detail="No Stripe billing profile exists for this account yet.",
            )
        session = await _stripe_request(
            "POST",
            "billing_portal/sessions",
            {
                "customer": customer_id,
                "return_url": f"{FRONTEND_URL}/#account",
            },
        )
        return {"mode": "stripe", "url": session["url"]}

    if DEV_BILLING:
        return {"mode": "dev", "url": None}
    raise HTTPException(status_code=503, detail="Billing is not configured.")


async def cancel_plan(user: dict) -> dict:
    subscription_id = user.get("stripe_subscription_id")
    if STRIPE_SECRET:
        if not subscription_id:
            raise HTTPException(
                status_code=503,
                detail="No Stripe subscription exists for this account.",
            )
        await _stripe_request(
            "POST",
            f"subscriptions/{subscription_id}",
            {"cancel_at_period_end": "true"},
        )
        return {"mode": "stripe", "canceled_at_period_end": True}

    if DEV_BILLING:
        downgrade_to_free(user["id"])
        return {"mode": "dev", "downgraded": True}

    raise HTTPException(status_code=503, detail="Billing is not configured.")


def _verify_signature(payload: bytes, header: str) -> None:
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="Webhook secret is not configured.")
    parts = {}
    for item in header.split(","):
        key, _, value = item.partition("=")
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")
    if abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(status_code=400, detail="Webhook timestamp is too old.")
    signed = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        signed.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")


async def handle_webhook(request: Request) -> dict:
    payload = await request.body()
    _verify_signature(payload, request.headers.get("stripe-signature", ""))
    event = json.loads(payload)
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {}) or {}
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id") or obj.get("client_reference_id")

    if event_type == "checkout.session.completed" and user_id:
        plan = metadata.get("plan")
        interval = metadata.get("interval", "month")
        if plan in PLANS:
            set_plan(user_id, plan, interval)
            with get_db() as connection:
                connection.execute(
                    "UPDATE users SET stripe_customer_id = ?, "
                    "stripe_subscription_id = ? WHERE id = ?",
                    (
                        obj.get("customer"),
                        obj.get("subscription"),
                        user_id,
                    ),
                )

    elif event_type in {
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        if user_id:
            status = obj.get("status")
            plan = metadata.get("plan", "free")
            interval = metadata.get("interval", "month")
            if event_type == "customer.subscription.deleted" or status in {
                "canceled",
                "unpaid",
                "incomplete_expired",
            }:
                downgrade_to_free(user_id)
            elif plan in PLANS:
                set_plan(user_id, plan, interval)
            with get_db() as connection:
                connection.execute(
                    "UPDATE users SET stripe_subscription_id = ? WHERE id = ?",
                    (obj.get("id"), user_id),
                )

    return {"received": True}
