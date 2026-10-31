"""Machine-readable error codes returned by the API.

Every error response is ``{"code": <ErrorCode>, "detail": <text>}``. The
frontend translates ``code`` (src/locales/*.ts, key ``errors``); ``detail``
is English, technical, and meant for logs and developers.
"""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    # request validation (400 / 404 / 422)
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    INVALID_FILE_ID = "INVALID_FILE_ID"
    INVALID_PATH = "INVALID_PATH"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    # the input is valid but cannot be converted (422)
    UNSUPPORTED_CONVERSION = "UNSUPPORTED_CONVERSION"
    EBOOK_DRM_PROTECTED = "EBOOK_DRM_PROTECTED"
    EBOOK_KFX = "EBOOK_KFX"
    EBOOK_INVALID = "EBOOK_INVALID"
    MEDIA_NO_AUDIO = "MEDIA_NO_AUDIO"
    MEDIA_NO_VIDEO = "MEDIA_NO_VIDEO"
    # server side (500)
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    CONVERSION_FAILED = "CONVERSION_FAILED"


class ApiError(Exception):
    """An error with an HTTP status, raised at the API boundary."""

    def __init__(self, status: int, code: ErrorCode, detail: str = ""):
        self.status = status
        self.code = code
        self.detail = detail or code.value
        super().__init__(self.detail)

    def body(self) -> dict:
        return {"code": self.code.value, "detail": self.detail}


class EbookInputError(ValueError):
    """The file cannot be converted for a reason the user must see
    (DRM, KFX, not a Kindle book, a video without sound...). Answered with 422."""

    def __init__(self, code: ErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class DependencyMissing(RuntimeError):
    """A system program or optional package needed for this conversion is
    not installed on the server. Answered with 500, like any RuntimeError."""

    code = ErrorCode.DEPENDENCY_MISSING
