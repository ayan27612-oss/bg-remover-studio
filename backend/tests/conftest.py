"""Test environment overrides applied before the application is imported."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="cutout-tests-"))

os.environ.setdefault("CUTOUT_DATA_DIR", str(TEST_DATA_DIR / "data"))
os.environ.setdefault("CUTOUT_CACHE_DIR", str(TEST_DATA_DIR / "jobs"))
os.environ.setdefault("GUEST_DAILY_LIMIT", "1000")
os.environ.setdefault("GUEST_MAX_DIMENSION", "1024")
os.environ.setdefault("CUTOUT_DEV_BILLING", "true")
os.environ.setdefault("PBKDF2_ITERATIONS", "50000")
os.environ.setdefault("PRELOAD_MODELS", "")
