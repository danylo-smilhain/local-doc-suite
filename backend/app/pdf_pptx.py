"""PDF -> PPTX: one slide per page, the page as a picture, its text in the notes.

pandoc cannot read PDF, and rebuilding a designed page (Canva, Keynote, a
PowerPoint export) as editable PowerPoint shapes would scatter its text and
fonts. So each page is rendered as a picture filling its slide, exactly as
it looks, and the page text goes to the speaker notes, where it can still be
copied and searched. A scanned page has no text layer: its text comes from
OCR (Tesseract), as the "with OCR" in the tool's description promises.
"""
import logging
import re

import fitz
from pptx import Presentation
from pptx.util import Emu

from app.ocr import (OCR_LANG_SAMPLE_PAGES, _choose_ocr_lang_order, _ocr_png, _render_page_png,
                     available_ocr_lang, page_needs_ocr)

logger = logging.getLogger(__name__)

# PowerPoint's default 16:9 slide is 13.333 in wide; the longer side of every
# slide gets that length, the other side follows the page's proportions.
SLIDE_LONG_SIDE_EMU = 12192000
# Longer side of the page picture: sharp on a 2560-pixel (1440p) screen.
PICTURE_LONG_SIDE_PX = 2560
JPEG_QUALITY = 90
# Characters XML 1.0 does not allow; PDF text may carry them (\x0c, \x0b...).
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def slide_size(width_pt: float, height_pt: float) -> tuple[int, int]:
    """Slide (width, height) in EMU with the page's proportions."""
    if width_pt >= height_pt:
        return SLIDE_LONG_SIDE_EMU, round(SLIDE_LONG_SIDE_EMU * height_pt / width_pt)
    return round(SLIDE_LONG_SIDE_EMU * width_pt / height_pt), SLIDE_LONG_SIDE_EMU


def fit_box(page_w: float, page_h: float, slide_w: int, slide_h: int) -> tuple[int, int, int, int]:
    """(left, top, width, height) of a page picture fitted and centred in the
    slide. A page with the slide's proportions fills it exactly; in a PDF that
    mixes page sizes the others are letterboxed, not stretched."""
    scale = min(slide_w / page_w, slide_h / page_h)
    w, h = round(page_w * scale), round(page_h * scale)
    if abs(w - slide_w) <= 1 and abs(h - slide_h) <= 1:
        return 0, 0, slide_w, slide_h
    return (slide_w - w) // 2, (slide_h - h) // 2, w, h


def notes_text(text: str) -> str:
    """Page text fit for the notes: without the control characters XML 1.0
    forbids (PDF text may carry \x0c, \x0b...), which python-pptx rejects."""
    return _XML_INVALID.sub("", text).strip()


def _page_picture(page) -> bytes:
    zoom = PICTURE_LONG_SIDE_PX / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes(output="jpg", jpg_quality=JPEG_QUALITY)


def _ocr_scans(doc, scans: list[int], lang: str) -> dict[int, str]:
    """OCR text of the scanned pages. As in PDF -> TXT, a few pages are read
    first to choose the language order (_choose_ocr_lang_order): with
    Ukrainian tried first, English text comes out in look-alike Cyrillic."""
    samples = {i: _ocr_png(_render_page_png(doc[i]), lang) for i in scans[:OCR_LANG_SAMPLE_PAGES]}
    ordered = _choose_ocr_lang_order(list(samples.values()), lang)
    if ordered != lang:
        samples = {}
    return {i: samples[i] if i in samples else _ocr_png(_render_page_png(doc[i]), ordered) for i in scans}


def pdf_to_pptx(in_path: str, out_path: str) -> list[str]:
    """Writes the presentation; returns warnings for the user."""
    import io

    import pytesseract

    warnings: list[str] = []
    try:
        pytesseract.get_tesseract_version()
        ocr_lang = available_ocr_lang()
    except Exception:
        logger.debug("Tesseract unavailable for PDF -> PPTX notes", exc_info=True)
        ocr_lang = None
    doc = fitz.open(in_path)
    try:
        first = doc[0].rect
        prs = Presentation()
        prs.slide_width, prs.slide_height = (Emu(v) for v in slide_size(first.width, first.height))
        blank = prs.slide_layouts[6]
        scans = [p.number for p in doc if page_needs_ocr(p)]
        ocr_text = _ocr_scans(doc, scans, ocr_lang) if ocr_lang and scans else {}
        for page in doc:
            slide = prs.slides.add_slide(blank)
            left, top, w, h = fit_box(page.rect.width, page.rect.height, prs.slide_width, prs.slide_height)
            slide.shapes.add_picture(io.BytesIO(_page_picture(page)), Emu(left), Emu(top), Emu(w), Emu(h))
            text = notes_text(ocr_text.get(page.number, page.get_text()))
            if text:
                slide.notes_slide.notes_text_frame.text = text
        if scans and not ocr_lang:
            warnings.append(f"Tesseract is not installed: the text of {len(scans)} scanned "
                            "page(s) was not recognised into the slide notes.")
        prs.save(out_path)
    finally:
        doc.close()
    return warnings
