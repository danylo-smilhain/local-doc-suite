"""Parsing of untrusted request values. Each function either returns a
value the rest of the code can trust or raises ApiError (4xx)."""
from __future__ import annotations

import re
import unicodedata
import uuid
from pathlib import Path

from .errors import ApiError, ErrorCode
from .models import OUTPUT_EXTS, SourceExt, TargetFormat


def parse_source_ext(raw: str | None) -> SourceExt:
    try:
        return SourceExt(raw)
    except ValueError:
        raise ApiError(400, ErrorCode.UNSUPPORTED_FORMAT, f"Unsupported file type: {raw!r}") from None


def ext_from_filename(filename: str | None) -> SourceExt:
    """Same rule the upload always used (text after the last dot, lower-case),
    then checked against the whitelist."""
    if not filename or "." not in filename:
        raise ApiError(400, ErrorCode.UNSUPPORTED_FORMAT, "File has no extension")
    return parse_source_ext(filename.split(".")[-1].lower())


def parse_target_format(raw: str | None) -> TargetFormat:
    try:
        return TargetFormat(raw)
    except ValueError:
        raise ApiError(400, ErrorCode.UNSUPPORTED_FORMAT, f"Unsupported target format: {raw!r}") from None


def parse_uuid(raw: str) -> str:
    """Canonical lower-case UUID string, exactly as /api/upload returns it."""
    try:
        canonical = str(uuid.UUID(raw))
    except (ValueError, TypeError, AttributeError):
        raise ApiError(400, ErrorCode.INVALID_FILE_ID, f"Invalid file id: {raw!r}") from None
    if canonical != raw:
        raise ApiError(400, ErrorCode.INVALID_FILE_ID, f"Invalid file id: {raw!r}")
    return canonical


def parse_file_ids(raw: str | None) -> list[str]:
    """``file_id`` form field: one UUID, or several joined by commas (merge)."""
    parts = (raw or "").split(",")
    return [parse_uuid(p) for p in parts]


def inside(base: Path, name: str) -> Path:
    """``base / name`` resolved; refuses anything that lands outside ``base``."""
    root = base.resolve()
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ApiError(400, ErrorCode.INVALID_PATH, "Path is outside storage")
    return path


_DOWNLOAD_ID = re.compile(r"^(converted|merged)_([0-9a-f-]{36})\.([a-z0-9]+)$")


def parse_download_id(raw: str) -> str:
    m = _DOWNLOAD_ID.match(raw or "")
    if not m or m.group(3) not in OUTPUT_EXTS:
        raise ApiError(404, ErrorCode.FILE_NOT_FOUND, "No such result")
    parse_uuid(m.group(2))
    return raw


# Keep the user's file name as it is; replace only what breaks a file name or a
# header: Windows-reserved characters, control characters and the bidi/line
# separators that can disguise an extension ("gnp\u202etxt.exe").
_UNSAFE_NAME_CHAR = re.compile('[<>:"|?*\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u2028\\u2029\\u202a-\\u202e\\u2066-\\u2069]')
MAX_NAME_LEN = 200


def sanitize_download_name(name: str | None) -> str | None:
    """Basename only, safe characters only. ``None`` when nothing usable is left."""
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    base = unicodedata.normalize("NFC", base)
    base = _UNSAFE_NAME_CHAR.sub("_", base).strip(" .")
    if not base or set(base) <= {"_", "."}:
        return None
    if len(base) > MAX_NAME_LEN:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: MAX_NAME_LEN - len(ext) - 1] + dot + ext) if dot and len(ext) < 16 else base[:MAX_NAME_LEN]
    return base
