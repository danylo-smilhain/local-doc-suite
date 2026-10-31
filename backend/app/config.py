"""Filesystem layout. Everything the server writes lives under STORAGE_DIR.

STORAGE_DIR defaults to ./storage relative to the working directory the
server starts in (the original behavior) and can be moved with the
LOCAL_DOC_STORAGE environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

STORAGE_DIR = Path(os.environ.get("LOCAL_DOC_STORAGE", "storage")).resolve()
UPLOAD_PATH = STORAGE_DIR / "uploads"
OUTPUT_PATH = STORAGE_DIR / "outputs"
CACHE_PATH = STORAGE_DIR / "cache"

# String forms: the conversion code builds paths with os.path.join.
UPLOAD_DIR = str(UPLOAD_PATH)
OUTPUT_DIR = str(OUTPUT_PATH)
OCR_CACHE_DIR = str(CACHE_PATH)


def ensure_storage() -> None:
    for d in (UPLOAD_PATH, OUTPUT_PATH, CACHE_PATH):
        d.mkdir(parents=True, exist_ok=True)


ensure_storage()


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Default logging for the server process (LOG_LEVEL, default INFO).
    No-op when the host (uvicorn --log-config, pytest) already configured it."""
    import logging
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format=LOG_FORMAT)
