"""Integration tests for the FastAPI studio API."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

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
    draw.rectangle((120, 130, 200, 235), fill=(20, 70, 190))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def background_png() -> bytes:
    image = Image.new("RGB", (500, 300), (20, 120, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 250, 300), fill=(240, 180, 20))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_root_and_health(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["version"]

    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert "u2net" in payload["supported_models"]
    assert payload["providers"]


def test_models(client: TestClient) -> None:
    response = client.get("/api/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default"] == "u2net"
    ids = {model["id"] for model in payload["models"]}
    assert ids == {"u2net", "u2netp", "isnet-general-use"}


def test_remove_transparent_png(client: TestClient, sample_png: bytes) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp", "output_format": "png"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-model"] == "u2netp"
    assert response.headers["x-image-width"] == "320"
    assert response.headers["x-image-height"] == "240"
    assert int(response.headers["x-processing-time-ms"]) >= 0

    result = Image.open(io.BytesIO(response.content))
    assert result.mode == "RGBA"
    assert result.size == (320, 240)
    assert result.getchannel("A").getextrema() == (0, 255)


def test_remove_webp_with_gradient(client: TestClient, sample_png: bytes) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={
            "model": "u2netp",
            "output_format": "webp",
            "quality": "82",
            "background_mode": "gradient",
            "gradient_from": "#101828",
            "gradient_to": "#f97316",
            "gradient_angle": "45",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/webp"
    result = Image.open(io.BytesIO(response.content))
    assert result.size == (320, 240)


def test_remove_with_custom_background_image(
    client: TestClient, sample_png: bytes, background_png: bytes
) -> None:
    response = client.post(
        "/api/remove",
        files={
            "image": ("subject.png", sample_png, "image/png"),
            "background_image": ("background.png", background_png, "image/png"),
        },
        data={
            "model": "u2netp",
            "background_mode": "image",
            "background_blur": "2",
        },
    )
    assert response.status_code == 200, response.text
    result = Image.open(io.BytesIO(response.content))
    assert result.size == (320, 240)


def test_alpha_matting(client: TestClient, sample_png: bytes) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={
            "model": "u2netp",
            "alpha_matting": "true",
            "foreground_threshold": "235",
            "background_threshold": "15",
            "erode_size": "8",
            "edge_feather": "0.8",
        },
    )
    assert response.status_code == 200, response.text
    result = Image.open(io.BytesIO(response.content))
    assert result.mode == "RGBA"


def test_max_dimension_resize(client: TestClient, sample_png: bytes) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp", "max_dimension": "256"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-image-width"] == "256"
    assert response.headers["x-original-width"] == "320"


def test_rejects_invalid_image(client: TestClient) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("broken.png", b"not an image", "image/png")},
        data={"model": "u2netp"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


def test_rejects_unsupported_content_type(client: TestClient) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("notes.txt", b"hello", "text/plain")},
        data={"model": "u2netp"},
    )
    assert response.status_code == 415


def test_rejects_invalid_thresholds(client: TestClient, sample_png: bytes) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={
            "model": "u2netp",
            "alpha_matting": "true",
            "foreground_threshold": "10",
            "background_threshold": "20",
        },
    )
    assert response.status_code == 422


def test_requires_background_image_for_image_mode(
    client: TestClient, sample_png: bytes
) -> None:
    response = client.post(
        "/api/remove",
        files={"image": ("subject.png", sample_png, "image/png")},
        data={"model": "u2netp", "background_mode": "image"},
    )
    assert response.status_code == 422
