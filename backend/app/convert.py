"""Conversion dispatch: which handler turns (source, target) into a file.

Two registries replace the old 300-line ``if/elif`` chain in
``convert_document``: ``SINGLE`` for one upload and ``MERGE`` for several.
A key is ``(source_ext, out_ext)``; ``ANY`` stands for "every other value".
``resolve`` looks a pair up in this order, which reproduces the order of the
old chain:

    exact (source, target) -> (source, ANY) -> (ANY, target) -> default

Handlers write ``job.out_path`` and record what happened on ``job.outcome``.
They raise; the API layer turns exceptions into HTTP errors.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Callable

from pdf2docx import Converter
from pypdf import PdfWriter

from app.config import OUTPUT_DIR
from app.ebooks.azw3 import azw3_epub_cached, epub_to_azw3
from app.ebooks.book_format import format_book_docx
from app.ebooks.epub import epub_to_pdf
from app.encoding import read_text_file
from app.engines import LIBREOFFICE_PDF_SOURCES, engine_libreoffice, engine_pandoc
from app.errors import DependencyMissing, EbookInputError, ErrorCode
from app.media import video_to_mp3, webm_to_mp4
from app.merge import convert_to_text_format, merge_docx, merge_to_pdf
from app.ocr import _ocr_png, available_ocr_lang, extract_pdf_text_cached, pdf_text_layer_is_broken
from app.pdf_flow import (
    ocrmypdf_available,
    ocrmypdf_rebuild,
    pdf2docx_convert,
    pdf_ocr_to_docx,
    pdf_textlayer_to_docx,
)
from app.pdf_layout import pdf_layout_to_docx
from app.telegram import is_telegram_export, telegram_html_to_md
from app.txt import convert_txt_to_md, txt_file_to_md

logger = logging.getLogger(__name__)

ANY = "*"

# PDF -> DOCX: "layout" — page for page (pictures as background, text in
# frames at the original coordinates); "flow" — pdf2docx (text reflows, the
# layout and page count are not kept).
PDF_DOCX_DEFAULT_MODE = "layout"


@dataclass
class Outcome:
    """What a conversion reports back besides the file itself."""
    engine: str | None = None
    layout: dict | None = None
    ocr_mode: str | None = None
    source_encoding: str | None = None
    warnings: list[str] = field(default_factory=list)
    temp_files: list[str] = field(default_factory=list)

    def warn(self, text: str | None) -> None:
        if text:
            self.warnings.append(text)


@dataclass
class Job:
    in_paths: list[str]
    out_path: str
    source: str
    target: str          # TargetFormat value as sent by the client (docx-ocr kept)
    out_ext: str         # extension of the produced file
    txt_smart: bool = True
    pdf_docx_mode: str | None = None
    file_id: str = ""
    outcome: Outcome = field(default_factory=Outcome)

    @property
    def in_path(self) -> str:
        return self.in_paths[0]


Handler = Callable[[Job], None]


def resolve(registry: dict, source: str, target: str, default: Handler) -> Handler:
    for key in ((source, target), (source, ANY), (ANY, target)):
        if key in registry:
            return registry[key]
    return default


def _tmp(prefix: str, ext: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{prefix}_{uuid.uuid4()}.{ext}")


def _remove(path: str | None) -> None:
    if path and os.path.exists(path):
        os.remove(path)


# ===========================================================================
# single file
# ===========================================================================

def pandoc_default(job: Job) -> None:
    engine_pandoc(job.in_path, job.out_path, job.out_ext, job.source)


def pdf_to_docx(job: Job) -> None:
    """Both "PDF -> Word" tools go through the page layout by default. The
    flow engine (pdf2docx) only on explicit pdf_docx_mode=flow for "docx";
    then a broken or scanned text layer is OCRed first."""
    out = job.outcome
    use_layout = job.target == "docx-ocr" or (
        job.target == "docx" and (job.pdf_docx_mode or PDF_DOCX_DEFAULT_MODE) != "flow")
    if use_layout:
        _pdf_layout(job)
    elif pdf_text_layer_is_broken(job.in_path):
        _pdf_ocr_flow(job)
    else:
        cv = Converter(job.in_path)
        try:
            cv.convert(job.out_path, start=0, end=None)
        finally:
            cv.close()
        out.engine = "pdf2docx"


def _pdf_layout(job: Job) -> None:
    out = job.outcome
    try:
        stats = pdf_layout_to_docx(job.in_path, job.out_path)
        out.engine = "layout"
    except Exception as e:  # any layout failure falls back to the flow engine
        error = f"{type(e).__name__}: {e}"
        logger.exception("Вёрстка не сохранена, потоковый режим: %s", error)
        pdf2docx_convert(job.in_path, job.out_path, strip_backgrounds=False)
        out.engine = "pdf2docx"
        out.warn("Не вдалося зберегти верстку, документ зібрано потоковим методом: " + error)
        return
    out.layout = stats
    if stats and stats.get("graphics_notes"):
        out.warn("Графіку збережено одним малюнком, не окремими об'єктами: "
                 + "; ".join(stats["graphics_notes"]))
    if stats and stats.get("ocr_pages"):
        out.warn(f"Розпізнано через OCR сторінок: {stats['ocr_pages']} з {stats['pages']}")
        out.ocr_mode = "tesseract"


def _pdf_ocr_flow(job: Job) -> None:
    out = job.outcome
    rebuilt = None
    if ocrmypdf_available():
        candidate = os.path.join(OUTPUT_DIR, f"ocr_{job.file_id}.pdf")
        if ocrmypdf_rebuild(job.in_path, candidate):
            rebuilt = candidate
            out.temp_files.append(candidate)
    if rebuilt:
        out.ocr_mode = "ocrmypdf"
        pdf_textlayer_to_docx(rebuilt, job.out_path)
    else:
        out.ocr_mode = "tesseract"
        pdf_ocr_to_docx(job.in_path, job.out_path)
    out.engine = "ocr-flow"
    out.warn("Текстовий шар PDF пошкоджено, документ розпізнано через OCR")


def pdf_to_text(job: Job) -> None:
    text = extract_pdf_text_cached(job.in_path)
    if job.out_ext == "md":
        text = convert_txt_to_md(text, smart=job.txt_smart)
    with open(job.out_path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# Image -> TXT / MD (OCR)
# ---------------------------------------------------------------------------
# Ordinary pictures are opened by Pillow. Camera RAW (.raw, .dng) is
# developed by rawpy (LibRaw); a DNG that Pillow can read (it is TIFF-based)
# works without it.

IMAGE_EXTS = ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp")
RAW_EXTS = ("raw", "dng")
# Photos usually carry no DPI; Tesseract assumes 70 without a hint and then
# misreads normal-sized text.
IMAGE_DEFAULT_DPI = 300
# Tesseract reads small text badly: images narrower than this are upscaled.
IMAGE_MIN_WIDTH = 1500


def _open_raw(path: str):
    """Camera RAW -> RGB PIL image via rawpy (LibRaw)."""
    from PIL import Image
    try:
        import rawpy
    except ImportError:
        raise DependencyMissing(
            "Camera RAW images need the 'rawpy' package (pip install rawpy) on the server.") from None
    try:
        with rawpy.imread(path) as raw:
            return Image.fromarray(raw.postprocess(use_camera_wb=True, output_bps=8))
    except (rawpy.LibRawError, ValueError) as e:
        raise EbookInputError(ErrorCode.UNSUPPORTED_FORMAT,
                              f"The RAW file could not be decoded: {e}") from e


def _image_frames(path: str, source: str) -> list:
    """Every page of the picture (multi-page TIFF/GIF give several), upright."""
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    try:
        img = Image.open(path)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        if source in RAW_EXTS:
            return [_open_raw(path)]
        raise EbookInputError(ErrorCode.UNSUPPORTED_FORMAT,
                              f"The file is not a readable {source.upper()} image.") from e
    # Phone photos are stored sideways with an EXIF "rotate me" flag.
    return [ImageOps.exif_transpose(frame.copy()) for frame in ImageSequence.Iterator(img)]


def _image_dpi(img) -> int:
    dpi = img.info.get("dpi")
    try:
        value = int(round(float(dpi[0]))) if dpi else 0
    except (TypeError, ValueError, IndexError):
        value = 0
    return value if value >= 70 else IMAGE_DEFAULT_DPI


def _ocr_ready_png(img) -> tuple[bytes, int]:
    """Grayscale, flattened onto white, upscaled when small -> (PNG bytes, DPI)."""
    from PIL import Image
    dpi = _image_dpi(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        img = Image.alpha_composite(white, rgba)
    img = img.convert("L")
    if img.width < IMAGE_MIN_WIDTH:
        factor = IMAGE_MIN_WIDTH / img.width
        img = img.resize((IMAGE_MIN_WIDTH, round(img.height * factor)), Image.LANCZOS)
        dpi = round(dpi * factor)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), dpi


def image_to_text(job: Job) -> None:
    """Image (PNG, JPG, TIFF, ..., camera RAW/DNG) -> TXT or Markdown via Tesseract."""
    import pytesseract
    lang = available_ocr_lang()
    pages = []
    try:
        for frame in _image_frames(job.in_path, job.source):
            png, dpi = _ocr_ready_png(frame)
            text = _ocr_png(png, lang, dpi=dpi).strip()
            if text:
                pages.append(text)
    except pytesseract.TesseractNotFoundError as e:
        raise DependencyMissing("Image OCR needs Tesseract installed on the server.") from e
    text = "\n\n".join(pages)
    if not text:
        job.outcome.warn("Текст на зображенні не розпізнано")
    if job.out_ext == "md":
        text = convert_txt_to_md(text, smart=job.txt_smart) if text else ""
    with open(job.out_path, "w", encoding="utf-8") as f:
        f.write(text + ("\n" if text and not text.endswith("\n") else ""))
    job.outcome.engine = "tesseract"
    job.outcome.ocr_mode = "tesseract"


def txt_to_md(job: Job) -> None:
    job.outcome.source_encoding = txt_file_to_md(job.in_path, job.out_path, smart=job.txt_smart)


def txt_via_md(job: Job) -> None:
    """TXT -> anything else: our own TXT -> MD first, then pandoc."""
    tmp_md = _tmp("tmp_txt", "md")
    job.outcome.source_encoding = txt_file_to_md(job.in_path, tmp_md, smart=job.txt_smart)
    try:
        engine_pandoc(tmp_md, job.out_path, job.out_ext, "md")
    finally:
        _remove(tmp_md)


def azw3_to_epub(job: Job) -> None:
    shutil.copyfile(azw3_epub_cached(job.in_path), job.out_path)


def azw3_to_pdf(job: Job) -> None:
    job.outcome.warn(epub_to_pdf(azw3_epub_cached(job.in_path), job.out_path))


def azw3_to_md(job: Job) -> None:
    engine_pandoc(azw3_epub_cached(job.in_path), job.out_path, "md", "epub")


def kindle_to_azw3(job: Job) -> None:
    epub_to_azw3(azw3_epub_cached(job.in_path), job.out_path)
    job.outcome.engine = "calibre"


def azw3_unsupported(job: Job) -> None:
    azw3_epub_cached(job.in_path)  # still reports DRM/KFX/damaged files first
    raise EbookInputError(ErrorCode.UNSUPPORTED_CONVERSION,
                          f"{job.source.upper()} cannot be converted to {job.out_ext.upper()}")


def epub_pdf(job: Job) -> None:
    """EPUB -> PDF: layout from the book's CSS (headings, title page, page
    breaks between spine files and before headings)."""
    job.outcome.warn(epub_to_pdf(job.in_path, job.out_path))


def fb2_to_pdf(job: Job) -> None:
    tmp_docx = _tmp("tmp", "docx")
    engine_pandoc(job.in_path, tmp_docx, "docx", job.source)
    format_book_docx(tmp_docx)
    pdf_res = engine_libreoffice(tmp_docx, OUTPUT_DIR, "pdf")
    shutil.move(pdf_res, job.out_path)
    _remove(tmp_docx)


def fb2_title_header(path: str) -> list[str]:
    """``# Author`` / ``## Title`` lines from the FB2 description."""
    header: list[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(50000)
    except OSError:
        logger.warning("Could not read FB2 header of %s", path, exc_info=True)
        return header
    first = re.findall(r"<first-name>(.*?)</first-name>", head)
    last = re.findall(r"<last-name>(.*?)</last-name>", head)
    title = re.findall(r"<book-title>(.*?)</book-title>", head)
    if first or last:
        author = f"{first[0] if first else ''} {last[0] if last else ''}".strip()
        if author:
            header.append(f"# {author}")
    if title:
        header.append(f"## {title[0]}")
    return header


def book_to_md(job: Job) -> None:
    """EPUB / FB2 -> Markdown; FB2 also gets the author and title on top."""
    header = fb2_title_header(job.in_path) if job.source == "fb2" else []
    engine_pandoc(job.in_path, job.out_path, job.out_ext, job.source)
    if header:
        with open(job.out_path, "r", encoding="utf-8") as f:
            body = f.read()
        if header[0] not in body:
            with open(job.out_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(header) + "\n\n---\n\n" + body)


def html_to_md(job: Job) -> None:
    """Telegram exports get their own parser: pandoc loses authors and dates."""
    html_text, job.outcome.source_encoding = read_text_file(job.in_path)
    if is_telegram_export(html_text):
        with open(job.out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(telegram_html_to_md(html_text))
    else:
        engine_pandoc(job.in_path, job.out_path, job.out_ext, job.source)


def html_to_pdf(job: Job) -> None:
    """A Telegram export goes the same way as a merge; other pages via LibreOffice."""
    if is_telegram_export(read_text_file(job.in_path)[0]):
        merge_to_pdf([job.in_path], job.source, job.out_path)
    else:
        office_to_pdf(job)


def office_to_pdf(job: Job) -> None:
    """Office formats -> PDF only through LibreOffice (pandoc needs LaTeX for
    PDF, which the image does not have, and cannot read PPTX at all)."""
    pdf_res = engine_libreoffice(job.in_path, OUTPUT_DIR, "pdf")
    shutil.move(pdf_res, job.out_path)


def doc_to_docx(job: Job) -> None:
    """Word 97-2003 -> DOCX straight through LibreOffice: it keeps fonts,
    colours, tables and page layout (pandoc cannot read .doc at all)."""
    # A private directory: two conversions of the same upload must not
    # overwrite each other's LibreOffice output (it is named after the input).
    workdir = tempfile.mkdtemp(prefix="doc_docx_", dir=OUTPUT_DIR)
    try:
        shutil.move(engine_libreoffice(job.in_path, workdir, "docx"), job.out_path)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def video_mp3(job: Job) -> None:
    video_to_mp3(job.in_path, job.out_path, "MP4" if job.source == "mp4" else "WebM")
    job.outcome.engine = "ffmpeg"


def webm_mp4(job: Job) -> None:
    webm_to_mp4(job.in_path, job.out_path)
    job.outcome.engine = "ffmpeg"


def mp3_unsupported(job: Job) -> None:
    raise EbookInputError(ErrorCode.UNSUPPORTED_CONVERSION, "MP3 can only be made from MP4 or WebM files.")


def azw3_target_unsupported(job: Job) -> None:
    raise EbookInputError(ErrorCode.UNSUPPORTED_CONVERSION, "AZW3 can only be made from MOBI files.")


def mp4_unsupported(job: Job) -> None:
    raise EbookInputError(ErrorCode.UNSUPPORTED_CONVERSION, "MP4 can only be made from WebM files.")


SINGLE: dict[tuple[str, str], Handler] = {
    ("pdf", "docx"): pdf_to_docx,
    ("pdf", "txt"): pdf_to_text,
    ("pdf", "md"): pdf_to_text,
    ("pdf", ANY): pandoc_default,
    ("txt", "md"): txt_to_md,
    ("txt", ANY): txt_via_md,
    ("azw3", "epub"): azw3_to_epub,
    ("azw3", "pdf"): azw3_to_pdf,
    ("azw3", "md"): azw3_to_md,
    ("azw3", ANY): azw3_unsupported,
    ("mobi", "epub"): azw3_to_epub,
    ("mobi", "azw3"): kindle_to_azw3,
    ("mobi", "pdf"): azw3_to_pdf,
    ("mobi", "md"): azw3_to_md,
    ("mobi", ANY): azw3_unsupported,
    ("epub", "pdf"): epub_pdf,
    ("fb2", "pdf"): fb2_to_pdf,
    ("epub", "md"): book_to_md,
    ("fb2", "md"): book_to_md,
    ("html", "md"): html_to_md,
    ("htm", "md"): html_to_md,
    ("html", "pdf"): html_to_pdf,
    ("htm", "pdf"): html_to_pdf,
    ("doc", "docx"): doc_to_docx,
    **{(src, "pdf"): office_to_pdf for src in sorted(LIBREOFFICE_PDF_SOURCES - {"html", "htm"})},
    **{(ext, target): image_to_text for ext in IMAGE_EXTS + RAW_EXTS for target in ("txt", "md")},
    ("mp4", "mp3"): video_mp3,
    ("webm", "mp3"): video_mp3,
    ("webm", "mp4"): webm_mp4,
    (ANY, "azw3"): azw3_target_unsupported,
    (ANY, "mp3"): mp3_unsupported,
    (ANY, "mp4"): mp4_unsupported,
}


# ===========================================================================
# several files
# ===========================================================================

def merge_pdfs(job: Job) -> None:
    merger = PdfWriter()
    for p in job.in_paths:
        merger.append(p)
    merger.write(job.out_path)
    merger.close()


def merge_into_pdf(job: Job) -> None:
    merge_to_pdf(job.in_paths, job.source, job.out_path)


def merge_into_docx(job: Job) -> None:
    merge_docx(job.in_paths, job.out_path)


def merge_txt_to_md(job: Job) -> None:
    parts = [convert_txt_to_md(read_text_file(p)[0], smart=True).strip() for p in job.in_paths]
    with open(job.out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n\n---\n\n".join(parts) + "\n")


def merge_books_via_markdown(in_paths: list[str], book_fmt: str, out_path: str) -> None:
    """Several EPUB/FB2 books -> one: each book to a temporary Markdown file
    (footnote labels made unique per book), joined with rules, then pandoc
    builds the result from the combined Markdown."""
    parts = []
    for p in in_paths:
        part_md = _tmp(f"part_{book_fmt}", "md")
        engine_pandoc(p, part_md, "md", book_fmt, footnote_prefix=f"b{len(parts) + 1}-")
        with open(part_md, "r", encoding="utf-8") as f:
            parts.append(f.read().strip())
        _remove(part_md)
    combined_md = _tmp("combined", "md")
    with open(combined_md, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(parts) + "\n")
    engine_pandoc(combined_md, out_path, book_fmt, "md")
    _remove(combined_md)


def merge_books(job: Job) -> None:
    merge_books_via_markdown(job.in_paths, job.source, job.out_path)


def merge_as_text(job: Job) -> None:
    """Each file converted to the target text format first, so that a .md
    never receives raw HTML (<div>, <!DOCTYPE html>...). A merge always has
    two or more inputs, so every part gets its number (footnote labels)."""
    parts = [convert_to_text_format(p, job.source, job.out_ext, first=(i == 0), part_no=i + 1)
             for i, p in enumerate(job.in_paths)]
    with open(job.out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n\n".join(x for x in parts if x) + "\n")


def merge_concat_then_pandoc(job: Job) -> None:
    temp_txt = _tmp("temp", "txt")
    with open(temp_txt, "w", encoding="utf-8") as f:
        for p in job.in_paths:
            text, _ = read_text_file(p)
            f.write(text.rstrip() + "\n\n")
    engine_pandoc(temp_txt, job.out_path, job.out_ext, job.source)


MERGE: dict[tuple[str, str], Handler] = {
    ("pdf", "pdf"): merge_pdfs,
    (ANY, "pdf"): merge_into_pdf,
    (ANY, "docx"): merge_into_docx,
    ("txt", "md"): merge_txt_to_md,
    ("epub", "epub"): merge_books,
    ("fb2", "fb2"): merge_books,
    (ANY, "txt"): merge_as_text,
    (ANY, "md"): merge_as_text,
    (ANY, "html"): merge_as_text,
}


def run(job: Job, merge: bool) -> None:
    registry, default = (MERGE, merge_concat_then_pandoc) if merge else (SINGLE, pandoc_default)
    handler = resolve(registry, job.source, job.out_ext, default)
    try:
        handler(job)
    finally:
        for tmp in job.outcome.temp_files:
            try:
                _remove(tmp)
            except OSError:
                logger.warning("Could not remove temporary file %s", tmp, exc_info=True)
