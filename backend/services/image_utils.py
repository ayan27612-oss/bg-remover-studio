"""Image decoding, normalisation, compositing and encoding helpers."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from schemas import BackgroundMode, OutputFormat

Image.MAX_IMAGE_PIXELS = 80_000_000

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/x-ms-bmp",
}
ALLOWED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


class ImageProcessingError(Exception):
    """Raised when an uploaded image cannot be decoded or processed."""


@dataclass(frozen=True)
class LoadedImage:
    image: Image.Image
    width: int
    height: int
    original_width: int
    original_height: int
    was_resized: bool
    source_format: Optional[str]


def load_image(data: bytes, max_dimension: Optional[int] = None) -> LoadedImage:
    """Decode an image, correct EXIF orientation and optionally downscale it."""

    if not data:
        raise ImageProcessingError("The uploaded image is empty.")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            source_format = probe.format
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageProcessingError("The file is not a valid or supported image.") from exc
    except Image.DecompressionBombError as exc:
        raise ImageProcessingError("The image dimensions are too large.") from exc

    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            oriented = ImageOps.exif_transpose(opened)
            image = _normalise_mode(oriented)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageProcessingError("The image could not be decoded.") from exc
    except Image.DecompressionBombError as exc:
        raise ImageProcessingError("The image dimensions are too large.") from exc

    original_width, original_height = image.size
    width, height = original_width, original_height
    was_resized = False

    if max_dimension is not None and max(width, height) > max_dimension:
        ratio = max_dimension / float(max(width, height))
        width = max(1, int(round(width * ratio)))
        height = max(1, int(round(height * ratio)))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        was_resized = True

    if width < 2 or height < 2:
        raise ImageProcessingError("The image must be at least 2x2 pixels.")

    return LoadedImage(
        image=image,
        width=width,
        height=height,
        original_width=original_width,
        original_height=original_height,
        was_resized=was_resized,
        source_format=source_format,
    )


def decode_background_image(data: bytes) -> Image.Image:
    """Decode a custom background image for compositing."""

    loaded = load_image(data, max_dimension=8192)
    return loaded.image


def _normalise_mode(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"}:
        return image.convert("RGBA")
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def parse_hex_color(value: str) -> tuple[int, int, int, int]:
    """Convert #rgb or #rrggbb into an RGBA tuple."""

    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    if len(value) != 6:
        raise ImageProcessingError(f"Invalid hex colour: #{value}")
    try:
        red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ImageProcessingError(f"Invalid hex colour: #{value}") from exc
    return red, green, blue, 255


def make_linear_gradient(
    size: tuple[int, int],
    start: str,
    end: str,
    angle: int,
) -> Image.Image:
    """Create a smooth two-stop linear gradient at any output size."""

    width, height = size
    start_rgba = np.asarray(parse_hex_color(start)[:3], dtype=np.float32)
    end_rgba = np.asarray(parse_hex_color(end)[:3], dtype=np.float32)

    # Generate a bounded intermediate image so multi-megapixel exports stay fast.
    scale = min(1.0, math.sqrt(1_000_000 / float(max(1, width * height))))
    gradient_width = max(2, int(round(width * scale)))
    gradient_height = max(2, int(round(height * scale)))

    x_values = np.linspace(0.0, 1.0, gradient_width, dtype=np.float32)
    y_values = np.linspace(0.0, 1.0, gradient_height, dtype=np.float32)
    x_grid, y_grid = np.meshgrid(x_values, y_values)

    radians = math.radians(angle)
    projection = x_grid * math.cos(radians) + y_grid * math.sin(radians)
    minimum = float(projection.min())
    maximum = float(projection.max())
    if maximum - minimum < 1e-6:
        projection = np.zeros_like(projection)
    else:
        projection = (projection - minimum) / (maximum - minimum)

    pixels = start_rgba[None, None, :] + (end_rgba - start_rgba)[None, None, :] * projection[
        ..., None
    ]
    gradient = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="RGB")
    gradient = gradient.resize((width, height), Image.Resampling.BICUBIC)
    return gradient.convert("RGBA")


def composite_background(
    foreground: Image.Image,
    mode: BackgroundMode,
    color: str,
    gradient_from: str,
    gradient_to: str,
    gradient_angle: int,
    blur: float,
    background_image: Optional[Image.Image] = None,
) -> Image.Image:
    """Place a transparent cutout over the requested background."""

    cutout = foreground.convert("RGBA")
    size = cutout.size

    if mode == BackgroundMode.TRANSPARENT:
        return cutout

    if mode == BackgroundMode.COLOR:
        canvas = Image.new("RGBA", size, parse_hex_color(color))
    elif mode == BackgroundMode.GRADIENT:
        canvas = make_linear_gradient(size, gradient_from, gradient_to, gradient_angle)
    elif mode == BackgroundMode.IMAGE:
        if background_image is None:
            raise ImageProcessingError("A background image is required for image mode.")
        fitted = ImageOps.fit(
            background_image.convert("RGB"),
            size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        if blur > 0:
            fitted = fitted.filter(ImageFilter.GaussianBlur(radius=blur))
        canvas = fitted.convert("RGBA")
    else:  # pragma: no cover - defensive guard for future enum members
        raise ImageProcessingError(f"Unsupported background mode: {mode}")

    canvas.alpha_composite(cutout)
    return canvas


def feather_alpha(image: Image.Image, radius: float) -> Image.Image:
    """Soften the cutout edge without changing the colour channels."""

    if radius <= 0:
        return image
    alpha = image.getchannel("A").filter(ImageFilter.GaussianBlur(radius=radius))
    feathered = image.copy()
    feathered.putalpha(alpha)
    return feathered


def resize_for_export(
    image: Image.Image, max_dimension: Optional[int]
) -> Image.Image:
    """Downscale an image so its longest edge fits within max_dimension."""

    if max_dimension is None:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dimension:
        return image
    ratio = max_dimension / float(longest)
    size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    return image.resize(size, Image.Resampling.LANCZOS)


def encode_image(
    image: Image.Image,
    output_format: OutputFormat,
    quality: int,
) -> tuple[bytes, str]:
    """Encode an RGBA image as PNG, WebP or JPEG bytes."""

    buffer = io.BytesIO()
    if output_format == OutputFormat.PNG:
        image.save(buffer, format="PNG", compress_level=6)
        return buffer.getvalue(), "image/png"
    if output_format == OutputFormat.WEBP:
        image.save(buffer, format="WEBP", quality=quality, method=6)
        return buffer.getvalue(), "image/webp"
    if output_format == OutputFormat.JPG:
        backdrop = Image.new("RGBA", image.size, (255, 255, 255, 255))
        backdrop.alpha_composite(image.convert("RGBA"))
        backdrop.convert("RGB").save(
            buffer, format="JPEG", quality=quality, optimize=True
        )
        return buffer.getvalue(), "image/jpeg"
    raise ImageProcessingError(f"Unsupported output format: {output_format}")


def export_image(
    image: Image.Image,
    output_format: OutputFormat,
    max_dimension: Optional[int],
    quality: int,
) -> tuple[bytes, str, tuple[int, int]]:
    """Resize and encode a cutout for download."""

    prepared = resize_for_export(image.convert("RGBA"), max_dimension)
    data, media_type = encode_image(prepared, output_format, quality)
    return data, media_type, prepared.size
