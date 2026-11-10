"""FastAPI application for Cutout, a minimal background remover."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import onnxruntime as ort
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

import auth
import billing
import plans
from database import get_db, init_db
from schemas import (
    AuthRequest,
    AuthResponse,
    BackgroundMode,
    CheckoutRequest,
    CheckoutResponse,
    ErrorResponse,
    ExportRequest,
    HealthResponse,
    ModelName,
    ModelsResponse,
    OutputFormat,
    PlanInfo,
    PlansResponse,
    RemovalSettings,
    UsageResponse,
    UserResponse,
)
from services.image_utils import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    ImageProcessingError,
    decode_background_image,
    load_image,
)
from services.remover import (
    DEFAULT_MODEL,
    MODEL_CATALOG,
    ModelUnavailableError,
    export_cutout,
    loaded_models,
    process_job,
    warm_models,
)

APP_VERSION = "1.1.0"
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))

CACHE_DIR = Path(
    os.getenv("CUTOUT_CACHE_DIR", Path(__file__).resolve().parent / "data" / "jobs")
)
JOB_TTL_HOURS = max(1, int(os.getenv("JOB_TTL_HOURS", "48")))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("cutout")

EXPOSED_HEADERS = [
    "X-Image-Width",
    "X-Image-Height",
    "X-Original-Width",
    "X-Original-Height",
    "X-Processing-Time-Ms",
    "X-Model",
    "X-Output-Format",
    "X-File-Size",
    "X-Metadata",
    "X-Job-Id",
    "X-Plan",
    "X-Usage-Used",
    "X-Usage-Limit",
    "X-Usage-Remaining",
    "Content-Disposition",
]


def _allowed_origins() -> list[str]:
    raw = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,"
        "http://127.0.0.1:4173",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


def _cleanup_jobs() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=JOB_TTL_HOURS)).isoformat()
    try:
        with get_db() as connection:
            rows = connection.execute(
                "SELECT cache_path FROM jobs WHERE created_at < ?", (cutoff,)
            ).fetchall()
            for row in rows:
                try:
                    Path(row["cache_path"]).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove cached job %s", row["cache_path"])
            connection.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
    except Exception:
        logger.exception("Job cache cleanup failed")


def _cleanup_sessions() -> None:
    try:
        with get_db() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at < ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
    except Exception:
        logger.exception("Session cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.inference_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    init_db()
    _cleanup_jobs()
    _cleanup_sessions()

    preload = [item.strip() for item in os.getenv("PRELOAD_MODELS", "").split(",")]
    models = [ModelName(item) for item in preload if item in ModelName._value2member_map_]
    if models:
        logger.info("Warming models: %s", ", ".join(model.value for model in models))
        warm_models(models)

    logger.info(
        "Cutout API v%s ready (billing=%s, max concurrent jobs=%s)",
        APP_VERSION,
        billing.billing_mode(),
        MAX_CONCURRENT_JOBS,
    )
    yield


app = FastAPI(
    title="Cutout API",
    description=(
        "Background removal powered by rembg and ONNX Runtime, with plans, "
        "usage limits and transparent PNG, WebP or JPG exports."
    ),
    version=APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=EXPOSED_HEADERS,
    max_age=86400,
)


@app.exception_handler(ImageProcessingError)
async def image_processing_error_handler(
    _request: Request, exc: ImageProcessingError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(detail=str(exc), code="invalid_image").model_dump(),
    )


@app.exception_handler(ModelUnavailableError)
async def model_unavailable_error_handler(
    _request: Request, exc: ModelUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(detail=str(exc), code="model_unavailable").model_dump(),
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": "Cutout API",
        "version": APP_VERSION,
        "docs": "/api/docs",
        "billing": billing.billing_mode(),
    }


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        onnxruntime_version=ort.__version__,
        providers=ort.get_available_providers(),
        loaded_models=loaded_models(),
        supported_models=list(MODEL_CATALOG.keys()),
    )


@app.get("/api/models", response_model=ModelsResponse, tags=["system"])
async def models() -> ModelsResponse:
    return ModelsResponse(default=DEFAULT_MODEL, models=list(MODEL_CATALOG.values()))


@app.get("/api/plans", response_model=PlansResponse, tags=["billing"])
async def get_plans() -> PlansResponse:
    return PlansResponse(
        plans=[PlanInfo(**plan) for plan in plans.public_plans()],
        billing_mode=billing.billing_mode(),
    )


@app.get("/api/usage", response_model=UsageResponse, tags=["account"])
async def get_usage(request: Request) -> UsageResponse:
    user = auth.get_user(request)
    return UsageResponse(**plans.usage_for(request, user))


@app.post("/api/auth/signup", response_model=AuthResponse, tags=["account"])
async def signup(payload: AuthRequest) -> AuthResponse:
    email = auth.normalise_email(payload.email)
    auth.validate_password(payload.password)
    user_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_db() as connection:
            connection.execute(
                "INSERT INTO users (id, email, password_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, email, auth.hash_password(payload.password), now),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="An account with that email already exists."
        ) from exc

    token = auth.create_session(user_id)
    user = auth.get_user_by_id(user_id)
    assert user is not None
    return AuthResponse(token=token, user=UserResponse(**auth.public_user(user)))


@app.post("/api/auth/login", response_model=AuthResponse, tags=["account"])
async def login(payload: AuthRequest) -> AuthResponse:
    email = auth.normalise_email(payload.email)
    user = auth.get_user_by_email(email)
    if user is None or not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token = auth.create_session(user["id"])
    return AuthResponse(token=token, user=UserResponse(**auth.public_user(user)))


@app.post("/api/auth/logout", tags=["account"])
async def logout(request: Request) -> dict[str, bool]:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        auth.destroy_session(token.strip())
    return {"ok": True}


@app.get("/api/auth/me", response_model=UserResponse, tags=["account"])
async def me(request: Request) -> UserResponse:
    user = auth.require_user(request)
    return UserResponse(**auth.public_user(user))


@app.post("/api/billing/checkout", response_model=CheckoutResponse, tags=["billing"])
async def checkout(payload: CheckoutRequest, request: Request) -> CheckoutResponse:
    user = auth.require_user(request)
    result = await billing.create_checkout(user, payload.plan, payload.interval)
    response = CheckoutResponse(**result)
    if result.get("upgraded"):
        updated = auth.get_user_by_id(user["id"])
        if updated:
            response.user = UserResponse(**auth.public_user(updated))
        response.usage = UsageResponse(**plans.usage_for(request, updated))
    return response


@app.post("/api/billing/portal", response_model=CheckoutResponse, tags=["billing"])
async def portal(request: Request) -> CheckoutResponse:
    user = auth.require_user(request)
    result = await billing.create_portal(user)
    return CheckoutResponse(**result)


@app.post("/api/billing/cancel", response_model=CheckoutResponse, tags=["billing"])
async def cancel(request: Request) -> CheckoutResponse:
    user = auth.require_user(request)
    result = await billing.cancel_plan(user)
    response = CheckoutResponse(**result)
    updated = auth.get_user_by_id(user["id"])
    if updated:
        response.user = UserResponse(**auth.public_user(updated))
        response.usage = UsageResponse(**plans.usage_for(request, updated))
    return response


@app.post("/api/billing/webhook", tags=["billing"])
async def webhook(request: Request) -> dict[str, bool]:
    return await billing.handle_webhook(request)


async def _read_upload(upload: UploadFile, label: str) -> bytes:
    content_type = (upload.content_type or "").lower()
    extension = Path(upload.filename or "").suffix.lower()
    if content_type not in ALLOWED_CONTENT_TYPES and extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"{label} must be a PNG, JPEG, WebP, BMP or TIFF image "
                f"(received {content_type or 'unknown type'})."
            ),
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{label} exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    await upload.close()

    if total == 0:
        raise HTTPException(status_code=400, detail=f"{label} is empty.")
    return b"".join(chunks)


def _build_settings(
    model: ModelName,
    alpha_matting: bool,
    foreground_threshold: int,
    background_threshold: int,
    erode_size: int,
    edge_feather: float,
    post_process_mask: bool,
    decontaminate: bool,
    output_format: OutputFormat,
    quality: int,
    background_mode: BackgroundMode,
    background_color: str,
    gradient_from: str,
    gradient_to: str,
    gradient_angle: int,
    background_blur: float,
    max_dimension: Optional[int],
) -> RemovalSettings:
    try:
        return RemovalSettings(
            model=model,
            alpha_matting=alpha_matting,
            foreground_threshold=foreground_threshold,
            background_threshold=background_threshold,
            erode_size=erode_size,
            edge_feather=edge_feather,
            post_process_mask=post_process_mask,
            decontaminate=decontaminate,
            output_format=output_format,
            quality=quality,
            background_mode=background_mode,
            background_color=background_color,
            gradient_from=gradient_from,
            gradient_to=gradient_to,
            gradient_angle=gradient_angle,
            background_blur=background_blur,
            max_dimension=max_dimension,
        )
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            messages.append(f"{location}: {error['msg']}")
        raise HTTPException(status_code=422, detail="; ".join(messages)) from exc


def _result_headers(
    result,
    job_id: str,
    plan_id: str,
    usage: dict,
) -> dict[str, str]:
    metadata = result.metadata
    return {
        "Cache-Control": "no-store",
        "X-Image-Width": str(metadata.width),
        "X-Image-Height": str(metadata.height),
        "X-Original-Width": str(metadata.original_width),
        "X-Original-Height": str(metadata.original_height),
        "X-Processing-Time-Ms": str(metadata.processing_ms),
        "X-Model": metadata.model.value,
        "X-Output-Format": metadata.output_format.value,
        "X-File-Size": str(metadata.file_size_bytes),
        "X-Job-Id": job_id,
        "X-Plan": plan_id,
        "X-Usage-Used": str(usage["used"]),
        "X-Usage-Limit": str(usage["limit"]),
        "X-Usage-Remaining": str(usage["remaining"]),
        "Content-Disposition": (
            f'inline; filename="cutout.{metadata.output_format.value}"'
        ),
        "X-Metadata": json.dumps(
            metadata.model_dump(mode="json"), separators=(",", ":")
        ),
    }


@app.post(
    "/api/remove",
    tags=["studio"],
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {}, "image/webp": {}, "image/jpeg": {}},
            "description": "Processed image bytes with metadata in response headers.",
        },
        400: {"model": ErrorResponse, "description": "Invalid image."},
        402: {"description": "Usage limit reached."},
        403: {"description": "Plan limit reached."},
        413: {"description": "Upload too large."},
        422: {"description": "Invalid settings."},
        503: {"model": ErrorResponse, "description": "Model unavailable."},
    },
)
async def remove_endpoint(
    request: Request,
    image: UploadFile = File(..., description="Source image to process."),
    background_image: Optional[UploadFile] = File(
        default=None,
        description="Optional background image when background_mode=image.",
    ),
    model: ModelName = Form(default=DEFAULT_MODEL),
    alpha_matting: bool = Form(default=False),
    foreground_threshold: int = Form(default=240),
    background_threshold: int = Form(default=10),
    erode_size: int = Form(default=10),
    edge_feather: float = Form(default=0.0),
    post_process_mask: bool = Form(default=False),
    decontaminate: bool = Form(default=True),
    output_format: OutputFormat = Form(default=OutputFormat.PNG),
    quality: int = Form(default=90),
    background_mode: BackgroundMode = Form(default=BackgroundMode.TRANSPARENT),
    background_color: str = Form(default="#ffffff"),
    gradient_from: str = Form(default="#6366f1"),
    gradient_to: str = Form(default="#ec4899"),
    gradient_angle: int = Form(default=135),
    background_blur: float = Form(default=0.0),
    max_dimension: Optional[int] = Form(default=None),
) -> Response:
    user = auth.get_user(request)
    plans.enforce_quota(request, user)
    plan = plans.plan_for(user)
    export_dimension = plans.resolve_dimension(max_dimension, user)

    settings = _build_settings(
        model=model,
        alpha_matting=alpha_matting,
        foreground_threshold=foreground_threshold,
        background_threshold=background_threshold,
        erode_size=erode_size,
        edge_feather=edge_feather,
        post_process_mask=post_process_mask,
        decontaminate=decontaminate,
        output_format=output_format,
        quality=quality,
        background_mode=background_mode,
        background_color=background_color,
        gradient_from=gradient_from,
        gradient_to=gradient_to,
        gradient_angle=gradient_angle,
        background_blur=background_blur,
        max_dimension=export_dimension,
    )

    if settings.background_mode == BackgroundMode.IMAGE and background_image is None:
        raise HTTPException(
            status_code=422,
            detail="background_image is required when background_mode is 'image'.",
        )

    image_bytes = await _read_upload(image, "Image")
    background_bytes = (
        await _read_upload(background_image, "Background image")
        if background_image is not None
        else None
    )

    loaded = load_image(image_bytes, int(plan["max_dimension"]))
    background = (
        decode_background_image(background_bytes) if background_bytes is not None else None
    )

    semaphore: asyncio.Semaphore = request.app.state.inference_semaphore
    async with semaphore:
        result = await run_in_threadpool(process_job, loaded, settings, background)

    job_id = secrets.token_hex(16)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{job_id}.png"
    cache_path.write_bytes(result.cutout_png)

    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_db() as connection:
            connection.execute(
                "INSERT INTO jobs (id, user_id, client_id, created_at, width, height, "
                "model, cache_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    user["id"] if user else None,
                    None if user else plans.client_id_for(request),
                    now,
                    result.metadata.width,
                    result.metadata.height,
                    result.metadata.model.value,
                    str(cache_path),
                ),
            )
    except Exception:
        cache_path.unlink(missing_ok=True)
        logger.exception("Could not record job %s", job_id)
        raise HTTPException(
            status_code=500, detail="The image was processed but could not be saved."
        )

    usage = plans.usage_for(request, user)
    return Response(
        content=result.data,
        media_type=result.media_type,
        headers=_result_headers(result, job_id, plan["id"], usage),
    )


@app.post(
    "/api/jobs/{job_id}/export",
    response_class=Response,
    tags=["studio"],
    responses={
        200: {"content": {"image/png": {}, "image/webp": {}, "image/jpeg": {}}},
        403: {"description": "Plan limit reached."},
        404: {"description": "Job not found or expired."},
    },
)
async def export_endpoint(
    job_id: str, payload: ExportRequest, request: Request
) -> Response:
    user = auth.get_user(request)
    plan = plans.plan_for(user)

    with get_db() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="That image has expired.")
    if user:
        if row["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="This image belongs to someone else.")
    elif row["client_id"] != plans.client_id_for(request):
        raise HTTPException(status_code=403, detail="This image belongs to someone else.")

    if payload.output_format.value not in plan["formats"]:
        raise HTTPException(
            status_code=403,
            detail=f"{plan['name']} does not include {payload.output_format.value.upper()} exports.",
        )
    dimension = plans.resolve_dimension(payload.max_dimension, user)

    cache_path = Path(row["cache_path"])
    if not cache_path.exists():
        raise HTTPException(status_code=404, detail="That image has expired.")

    data = cache_path.read_bytes()
    encoded, media_type, (width, height) = await run_in_threadpool(
        export_cutout,
        data,
        payload.output_format,
        dimension,
        payload.quality,
    )

    usage = plans.usage_for(request, user)
    headers = {
        "Cache-Control": "no-store",
        "X-Image-Width": str(width),
        "X-Image-Height": str(height),
        "X-Output-Format": payload.output_format.value,
        "X-File-Size": str(len(encoded)),
        "X-Plan": plan["id"],
        "X-Usage-Used": str(usage["used"]),
        "X-Usage-Limit": str(usage["limit"]),
        "X-Usage-Remaining": str(usage["remaining"]),
        "Content-Disposition": (
            f'attachment; filename="cutout.{payload.output_format.value}"'
        ),
    }
    return Response(content=encoded, media_type=media_type, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
