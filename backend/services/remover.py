"""Background-removal engine with thread-safe model session caching."""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PIL import Image
from rembg import new_session, remove
from rembg.sessions.base import BaseSession

from schemas import (
    BackgroundMode,
    ModelInfo,
    ModelName,
    OutputFormat,
    RemovalMetadata,
    RemovalSettings,
)
from services.image_utils import (
    LoadedImage,
    composite_background,
    encode_image,
    export_image,
    feather_alpha,
)

logger = logging.getLogger(__name__)

MODEL_CATALOG: dict[ModelName, ModelInfo] = {
    ModelName.U2NET: ModelInfo(
        id=ModelName.U2NET,
        label="U²-Net",
        description=(
            "The reliable all-rounder. Strong, clean silhouettes for most "
            "photos, products and people."
        ),
        speed="Balanced",
        precision="High",
        recommended_for="General photos, products and portraits",
        approx_size_mb=176,
    ),
    ModelName.U2NETP: ModelInfo(
        id=ModelName.U2NETP,
        label="U²-Net Lite",
        description=(
            "A tiny, extremely fast model. Ideal for quick previews and "
            "simple subjects with crisp outlines."
        ),
        speed="Fastest",
        precision="Good",
        recommended_for="Quick previews, simple objects and batch drafts",
        approx_size_mb=5,
    ),
    ModelName.ISNET_GENERAL_USE: ModelInfo(
        id=ModelName.ISNET_GENERAL_USE,
        label="IS-Net Precision",
        description=(
            "High-precision segmentation with finer edges. Pair it with alpha "
            "matting for hair, fur and translucent materials."
        ),
        speed="Moderate",
        precision="Highest",
        recommended_for="Hair, fur, fine edges and final exports",
        approx_size_mb=176,
    ),
}

DEFAULT_MODEL = ModelName.U2NET

_sessions: dict[str, BaseSession] = {}
_sessions_lock = threading.Lock()


class ModelUnavailableError(Exception):
    """Raised when an inference model cannot be loaded."""


def get_session(model: ModelName) -> BaseSession:
    """Return a cached ONNX session, loading it at most once per process."""

    if model not in MODEL_CATALOG:
        raise ModelUnavailableError(f"Unsupported model: {model}")

    key = model.value
    cached = _sessions.get(key)
    if cached is not None:
        return cached

    with _sessions_lock:
        cached = _sessions.get(key)
        if cached is not None:
            return cached
        logger.info("Loading rembg model %s", key)
        try:
            session = new_session(key)
        except Exception as exc:  # rembg raises several dependency errors
            logger.exception("Failed to load rembg model %s", key)
            raise ModelUnavailableError(
                f"The {key} model could not be loaded. Check the server logs."
            ) from exc
        _sessions[key] = session
        logger.info("Loaded rembg model %s", key)
        return session


def loaded_models() -> list[str]:
    return sorted(_sessions.keys())


def warm_models(models: list[ModelName]) -> None:
    """Preload sessions in a background thread during application startup."""

    def _warm() -> None:
        for model in models:
            try:
                get_session(model)
            except ModelUnavailableError:
                logger.exception("Warm-up failed for %s", model.value)

    thread = threading.Thread(target=_warm, name="rembg-warmup", daemon=True)
    thread.start()


def remove_background(image: Image.Image, settings: RemovalSettings) -> Image.Image:
    """Run segmentation and optional alpha matting, returning an RGBA cutout."""

    session = get_session(settings.model)
    try:
        cutout = remove(
            image,
            session=session,
            alpha_matting=settings.alpha_matting,
            alpha_matting_foreground_threshold=settings.foreground_threshold,
            alpha_matting_background_threshold=settings.background_threshold,
            alpha_matting_erode_size=settings.erode_size,
            post_process_mask=settings.post_process_mask,
            decontaminate=settings.decontaminate and not settings.alpha_matting,
        )
    except Exception as exc:
        logger.exception("Background removal failed with model %s", settings.model.value)
        raise ModelUnavailableError("Background removal failed. Please retry.") from exc

    if not isinstance(cutout, Image.Image):
        cutout = Image.open(io.BytesIO(cutout))
    result = cutout.convert("RGBA")

    if settings.edge_feather > 0:
        result = feather_alpha(result, settings.edge_feather)
    return result


@dataclass(frozen=True)
class ProcessedJob:
    data: bytes
    media_type: str
    metadata: RemovalMetadata
    cutout_png: bytes


def _build_metadata(
    settings: RemovalSettings,
    loaded: LoadedImage,
    width: int,
    height: int,
    processing_ms: int,
    file_size_bytes: int,
) -> RemovalMetadata:
    return RemovalMetadata(
        model=settings.model,
        alpha_matting=settings.alpha_matting,
        output_format=settings.output_format,
        width=width,
        height=height,
        original_width=loaded.original_width,
        original_height=loaded.original_height,
        was_resized=(width, height)
        != (loaded.original_width, loaded.original_height),
        background_mode=settings.background_mode,
        processing_ms=processing_ms,
        file_size_bytes=file_size_bytes,
    )


def process_job(
    loaded: LoadedImage,
    settings: RemovalSettings,
    background_image: Optional[Image.Image] = None,
) -> ProcessedJob:
    """Segment a subject, cache the cutout and encode the requested export."""

    started = time.perf_counter()
    cutout = remove_background(loaded.image, settings)

    if settings.background_mode == BackgroundMode.IMAGE and background_image is None:
        raise ValueError("A background image is required for image mode.")

    composited = composite_background(
        foreground=cutout,
        mode=settings.background_mode,
        color=settings.background_color,
        gradient_from=settings.gradient_from,
        gradient_to=settings.gradient_to,
        gradient_angle=settings.gradient_angle,
        blur=settings.background_blur,
        background_image=background_image,
    )

    cutout_png, _ = encode_image(composited, OutputFormat.PNG, 90)
    data, media_type, (width, height) = export_image(
        composited,
        settings.output_format,
        settings.max_dimension,
        settings.quality,
    )
    processing_ms = int(round((time.perf_counter() - started) * 1000))

    metadata = _build_metadata(
        settings, loaded, width, height, processing_ms, len(data)
    )

    logger.info(
        "Processed image model=%s size=%sx%s alpha_matting=%s duration_ms=%s",
        settings.model.value,
        width,
        height,
        settings.alpha_matting,
        processing_ms,
    )
    return ProcessedJob(
        data=data,
        media_type=media_type,
        metadata=metadata,
        cutout_png=cutout_png,
    )


def export_cutout(
    cutout_png: bytes,
    output_format: OutputFormat,
    max_dimension: Optional[int],
    quality: int,
) -> tuple[bytes, str, tuple[int, int]]:
    """Re-encode a cached transparent cutout without running inference again."""

    with Image.open(io.BytesIO(cutout_png)) as image:
        image.load()
        return export_image(image, output_format, max_dimension, quality)
