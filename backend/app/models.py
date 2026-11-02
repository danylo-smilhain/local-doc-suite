"""Domain vocabulary: which formats exist and how they map to files.

Glossary
- source extension (SourceExt): extension of an uploaded file, lower-case,
  without the dot. It is also the suffix of the stored upload
  (``storage/uploads/<file_id>.<ext>``).
- target format (TargetFormat): what the client asks to produce. Usually
  the output extension; ``docx-ocr`` is a variant of ``docx``.
- output extension: suffix of the produced file (``TargetFormat.out_ext``).
- download id: basename of a produced file in ``storage/outputs``,
  ``converted_<file_id>.<ext>`` or ``merged_<uuid>.<ext>``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceExt(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    ODT = "odt"
    RTF = "rtf"
    PPTX = "pptx"
    PPT = "ppt"
    ODP = "odp"
    XLSX = "xlsx"
    XLS = "xls"
    ODS = "ods"
    HTML = "html"
    HTM = "htm"
    MD = "md"
    MARKDOWN = "markdown"
    TXT = "txt"
    EPUB = "epub"
    FB2 = "fb2"
    AZW3 = "azw3"
    MOBI = "mobi"
    MP4 = "mp4"
    WEBM = "webm"
    MP3 = "mp3"
    M4A = "m4a"
    TS = "ts"
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    TIF = "tif"
    TIFF = "tiff"
    BMP = "bmp"
    GIF = "gif"
    WEBP = "webp"
    RAW = "raw"
    DNG = "dng"


class TargetFormat(str, Enum):
    TXT = "txt"
    MD = "md"
    DOCX = "docx"
    DOCX_OCR = "docx-ocr"
    PDF = "pdf"
    EPUB = "epub"
    FB2 = "fb2"
    AZW3 = "azw3"
    PPTX = "pptx"
    HTML = "html"
    MP3 = "mp3"
    MP4 = "mp4"
    WEBM = "webm"

    @property
    def out_ext(self) -> str:
        return "docx" if self is TargetFormat.DOCX_OCR else self.value


OUTPUT_EXTS = frozenset(t.out_ext for t in TargetFormat)


# --- API responses -----------------------------------------------------------

class ConversionResponse(BaseModel):
    """Answer of POST /api/convert. Fields that are ``None`` are left out of
    the JSON, as before; ``warnings`` is always present."""

    status: Literal["success"] = "success"
    download_id: str
    meta: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    warning: str | None = None           # legacy: all warnings joined with "; "
    engine: str | None = None
    layout: dict[str, Any] | None = None
    ocr_mode: str | None = None
    source_encoding: str | None = None
