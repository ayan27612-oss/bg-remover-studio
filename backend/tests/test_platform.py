"""Integration tests for accounts, plans, billing and exports."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import plans
from main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def sample_png() -> bytes:
    image = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 20, 280, 220), fill=(198, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _signup(client: TestClient) -> dict:
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/auth/signup", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(account: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['token']}"}


def test_plans_catalog(client: TestClient) -> None:
    response = client.get("/api/plans")
    assert response.status_code == 200
    payload = response.json()
    assert payload["billing_mode"] in {"dev", "stripe"}
    plans_by_id = {plan["id"]: plan for plan in payload["plans"]}
    assert set(plans_by_id) == {"free", "pro", "business"}
    assert plans_by_id["pro"]["credits"] == 200
    assert plans_by_id["business"]["max_dimension"] == 8192


def test_signup_login_me_and_logout(client: TestClient) -> None:
    account = _signup(client)
    assert account["user"]["plan"] == "free"
    assert account["user"]["email"].endswith("@example.com")

    me = client.get("/api/auth/me", headers=_auth(account))
    assert me.status_code == 200
    assert me.json()["id"] == account["user"]["id"]

    bad_login = client.post(
        "/api/auth/login",
        json={"email": account["user"]["email"], "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"email": account["user"]["email"], "password": "password123"},
    )
    assert login.status_code == 200
    login_account = login.json()

    logout = client.post("/api/auth/logout", headers=_auth(login_account))
    assert logout.status_code == 200
    assert client.get("/api/auth/me", headers=_auth(login_account)).status_code == 401


def test_checkout_upgrades_and_cancel_downgrades(client: TestClient) -> None:
    account = _signup(client)
    checkout = client.post(
        "/api/billing/checkout",
        json={"plan": "pro", "interval": "year"},
        headers=_auth(account),
    )
    assert checkout.status_code == 200, checkout.text
    payload = checkout.json()
    assert payload["upgraded"] is True
    assert payload["user"]["plan"] == "pro"
    assert payload["user"]["plan_interval"] == "year"
    assert payload["usage"]["limit"] == 200
    assert payload["usage"]["max_dimension"] == 4096

    cancel = client.post("/api/billing/cancel", headers=_auth(account))
    assert cancel.status_code == 200
    assert cancel.json()["downgraded"] is True
    assert cancel.json()["user"]["plan"] == "free"


def test_remove_then_export_another_format(
    client: TestClient, sample_png: bytes
) -> None:
    headers = {"X-Client-Id": f"test-{uuid.uuid4().hex}"}
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp", "max_dimension": "512"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    job_id = response.headers["x-job-id"]
    assert response.headers["x-plan"] == "guest"
    assert response.headers["x-usage-used"] == "1"

    export = client.post(
        f"/api/jobs/{job_id}/export",
        json={"output_format": "jpg", "max_dimension": 256, "quality": 85},
        headers=headers,
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"] == "image/jpeg"
    assert export.headers["content-disposition"].startswith("attachment")
    result = Image.open(io.BytesIO(export.content))
    assert result.mode == "RGB"
    assert result.size == (256, 192)

    missing = client.post(
        f"/api/jobs/{uuid.uuid4().hex}/export",
        json={"output_format": "png"},
        headers=headers,
    )
    assert missing.status_code == 404


def test_free_plan_rejects_paid_resolution(
    client: TestClient, sample_png: bytes
) -> None:
    account = _signup(client)
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp", "max_dimension": "4096"},
        headers=_auth(account),
    )
    assert response.status_code == 403
    assert "1024" in response.json()["detail"]


def test_guest_quota_exhausted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, sample_png: bytes
) -> None:
    monkeypatch.setattr(plans, "GUEST_DAILY_LIMIT", 0)
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp"},
        headers={"X-Client-Id": f"quota-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 402
