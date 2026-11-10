"""Pydantic models shared by the background-removal API."""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ModelName(str, Enum):
    """Models exposed by the studio."""

    U2NET = "u2net"
    U2NETP = "u2netp"
    ISNET_GENERAL_USE = "isnet-general-use"


class OutputFormat(str, Enum):
    PNG = "png"
    WEBP = "webp"
    JPG = "jpg"


class BackgroundMode(str, Enum):
    TRANSPARENT = "transparent"
    COLOR = "color"
    GRADIENT = "gradient"
    IMAGE = "image"


class RemovalSettings(BaseModel):
    """Validated settings for a single background-removal job."""

    model_config = ConfigDict(extra="forbid")

    model: ModelName = Field(
        default=ModelName.U2NET,
        description="Segmentation model to use.",
    )
    alpha_matting: bool = Field(
        default=False,
        description="Enable alpha matting for hair, fur and other fine edges.",
    )
    foreground_threshold: int = Field(
        default=240,
        ge=0,
        le=255,
        description="Alpha-matting foreground threshold.",
    )
    background_threshold: int = Field(
        default=10,
        ge=0,
        le=255,
        description="Alpha-matting background threshold.",
    )
    erode_size: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Alpha-matting erosion size in pixels.",
    )
    edge_feather: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Gaussian blur applied to the alpha channel after inference.",
    )
    post_process_mask: bool = Field(
        default=False,
        description="Apply rembg's morphological mask post-processing.",
    )
    decontaminate: bool = Field(
        default=True,
        description="Remove background colour fringing from soft edges.",
    )
    output_format: OutputFormat = Field(default=OutputFormat.PNG)
    quality: int = Field(
        default=90,
        ge=1,
        le=100,
        description="WebP quality (ignored for PNG).",
    )
    background_mode: BackgroundMode = Field(default=BackgroundMode.TRANSPARENT)
    background_color: str = Field(default="#ffffff")
    gradient_from: str = Field(default="#6366f1")
    gradient_to: str = Field(default="#ec4899")
    gradient_angle: int = Field(default=135, ge=0, le=360)
    background_blur: float = Field(default=0.0, ge=0.0, le=40.0)
    max_dimension: Optional[int] = Field(
        default=None,
        ge=256,
        le=8192,
        description="Optionally downscale the working image before inference.",
    )

    @field_validator("background_color", "gradient_from", "gradient_to")
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        if not HEX_COLOR_PATTERN.fullmatch(value):
            raise ValueError("must be a hex colour such as #ffffff or #fff")
        return value.lower()

    @model_validator(mode="after")
    def validate_thresholds(self) -> "RemovalSettings":
        if self.foreground_threshold <= self.background_threshold:
            raise ValueError(
                "foreground_threshold must be greater than background_threshold"
            )
        return self


class ModelInfo(BaseModel):
    id: ModelName
    label: str
    description: str
    speed: str
    precision: str
    recommended_for: str
    approx_size_mb: int
    supports_alpha_matting: bool = True


class ModelsResponse(BaseModel):
    default: ModelName
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str
    version: str
    onnxruntime_version: str
    providers: list[str]
    loaded_models: list[str]
    supported_models: list[ModelName]


class ImageMetadata(BaseModel):
    width: int
    height: int
    original_width: int
    original_height: int
    was_resized: bool


class RemovalMetadata(BaseModel):
    model: ModelName
    alpha_matting: bool
    output_format: OutputFormat
    width: int
    height: int
    original_width: int
    original_height: int
    was_resized: bool
    background_mode: BackgroundMode
    processing_ms: int
    file_size_bytes: int


class ErrorResponse(BaseModel):
    detail: str
    code: str = "request_failed"


class AuthRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
    plan_interval: str
    plan_renews_at: Optional[str] = None
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class PlanInfo(BaseModel):
    id: str
    name: str
    tagline: str
    price_monthly: int
    price_yearly: int
    credits: int
    period: str
    max_dimension: int
    formats: list[str]
    highlighted: bool
    features: list[str]


class PlansResponse(BaseModel):
    plans: list[PlanInfo]
    billing_mode: str


class UsageResponse(BaseModel):
    authenticated: bool
    plan: str
    plan_name: str
    used: int
    limit: int
    remaining: int
    period: str
    resets_at: str
    max_dimension: int
    formats: list[str]


class CheckoutRequest(BaseModel):
    plan: str = Field(default="pro")
    interval: str = Field(default="month")


class CheckoutResponse(BaseModel):
    mode: str
    url: Optional[str] = None
    upgraded: bool = False
    canceled_at_period_end: bool = False
    downgraded: bool = False
    user: Optional[UserResponse] = None
    usage: Optional[UsageResponse] = None


class ExportRequest(BaseModel):
    output_format: OutputFormat = OutputFormat.PNG
    max_dimension: Optional[int] = Field(default=None, ge=256, le=8192)
    quality: int = Field(default=90, ge=1, le=100)
