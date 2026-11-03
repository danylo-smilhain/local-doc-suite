"""PDF -> PPTX page for page, the way PDF -> Word does it (app.pdf_layout).

Each page becomes one slide with the page's proportions:
- the background is the page rendered WITHOUT its text (pictures, colour,
  vector graphics stay), one picture locked in place so a click on the
  slide does not drag it;
- the text is on top as editable PowerPoint text boxes, one per line, in
  the same places, with the PDF's size, colour, bold and italic.

Where the text comes from (same rules and helpers as the Word layout):
- a normal text layer: _collect_page_text;
- a scan (no text layer) or a damaged text layer: OCR with Tesseract, but
  only for the "with OCR" tool (target "pptx-ocr"). Without OCR such a page
  stays a picture and the user is told to use the OCR tool.
A text layer whose ToUnicode table is broken is repaired first
(repair_pdf_tounicode), as PDF -> TXT does.
"""
import io
import logging

import fitz
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Emu, Pt

from app.ocr import (OCR_DPI, OCR_LANG_SAMPLE_PAGES, _choose_ocr_lang_order, _ocr_png, _render_page_png,
                     available_ocr_lang, page_text_is_broken, span_is_garbled)
from app.pdf_layout import (LAYOUT_BG_DPI, _collect_page_text, _image_bytes, _inpaint_boxes,
                            _layout_page_is_scan, _ocr_is_meaningful, _ocr_segments, _render_without_text,
                            _rotated_text_rects)
from app.pdf_text import repair_pdf_tounicode

logger = logging.getLogger(__name__)

# PowerPoint's default 16:9 slide is 13.333 in wide; the longer side of every
# slide gets that length, the other side follows the page's proportions.
SLIDE_LONG_SIDE_EMU = 12192000
EMU_PER_PT = 12700
# A PowerPoint text line puts its baseline about 0.9 em below the top of the
# box (typical ascent); the box is 1.25 em tall and a little wider than the
# PDF line so a substituted, slightly wider font does not run into the edge.
BASELINE_EM = 0.9
LINE_HEIGHT_EM = 1.25
WIDTH_SLACK_EM = 0.3
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def slide_size(width_pt: float, height_pt: float) -> tuple[int, int]:
    """Slide (width, height) in EMU with the page's proportions."""
    if width_pt >= height_pt:
        return SLIDE_LONG_SIDE_EMU, round(SLIDE_LONG_SIDE_EMU * height_pt / width_pt)
    return round(SLIDE_LONG_SIDE_EMU * width_pt / height_pt), SLIDE_LONG_SIDE_EMU


def fit_box(page_w: float, page_h: float, slide_w: int, slide_h: int) -> tuple[int, int, int, int]:
    """(left, top, width, height) of a page fitted and centred in the slide.
    A page with the slide's proportions fills it exactly; in a PDF that mixes
    page sizes the others are letterboxed, not stretched."""
    scale = min(slide_w / page_w, slide_h / page_h)
    w, h = round(page_w * scale), round(page_h * scale)
    if abs(w - slide_w) <= 1 and abs(h - slide_h) <= 1:
        return 0, 0, slide_w, slide_h
    return (slide_w - w) // 2, (slide_h - h) // 2, w, h


def line_box(runs: list[dict]) -> tuple[float, float, float, float]:
    """(left, top, width, height) in PDF points of the text box for one line
    of runs (as _collect_page_text / _ocr_segments give them), placed so its
    baseline falls on the PDF baseline."""
    size = max(r["size"] for r in runs)
    left = min(r["x0"] for r in runs)
    right = max(r["x1"] for r in runs)
    baseline = max(r["origin_y"] for r in runs)
    return left, baseline - BASELINE_EM * size, right - left + WIDTH_SLACK_EM * size, LINE_HEIGHT_EM * size


def scan_warning(pages: int, ocr: bool, tesseract: bool) -> str | None:
    """What to tell the user about pages whose text could not be made editable."""
    if not pages or (ocr and tesseract):
        return None
    if not ocr:
        return (f"{pages} page(s) have no usable text layer (a scan or damaged text), so they "
                "stay pictures; use PDF to PPTX (with OCR) to make their text editable.")
    return (f"Tesseract is not installed: the text of {pages} scanned page(s) "
            "was not recognised and they stay pictures.")


def _tesseract_lang() -> str | None:
    import pytesseract
    try:
        pytesseract.get_tesseract_version()
        return available_ocr_lang()
    except Exception:
        logger.debug("Tesseract unavailable for PDF -> PPTX", exc_info=True)
        return None


def _ocr_lang_order(doc, pages: list[int], lang: str) -> str:
    """As in PDF -> TXT: a few pages are read first to choose the language
    order; with Ukrainian tried first, English comes out in look-alike Cyrillic."""
    samples = [_ocr_png(_render_page_png(doc[i]), lang) for i in pages[:OCR_LANG_SAMPLE_PAGES]]
    return _choose_ocr_lang_order(samples, lang)


def _ocr_page(src, pno: int, broken: bool, lang: str):
    """(background, OCR segments) for a scan or a damaged text layer, as
    pdf_layout_to_docx does; segments are [] when nothing readable was found."""
    page = src[pno]
    if broken:
        _, rects = _collect_page_text(page)
        rects = rects or [fitz.Rect(b[:4]) for b in page.get_text("blocks")]
        bg = _render_without_text(src, pno, rects, OCR_DPI, keep=_rotated_text_rects(page))
    else:
        bg = _render_without_text(src, pno, [], OCR_DPI)
    full = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    full_img = Image.frombytes("RGB", (full.width, full.height), full.samples)
    try:
        segments, boxes = _ocr_segments(full_img, 72.0 / OCR_DPI, lang)
    except Exception as e:
        logger.warning(f"OCR of page {pno + 1} failed: {e}")
        segments, boxes = [], []
    if not (segments and _ocr_is_meaningful(segments)):
        return full_img, []
    if not broken:
        bg = _inpaint_boxes(bg, boxes)
    return bg, segments


def without_garbled(segments: list[dict]) -> list[dict]:
    """Segments with garbled runs (a font without a Unicode mapping) taken
    out; a line is cut where one was, so the text after it keeps its place
    instead of sliding left into the gap. Every run is judged as if its font
    were Type3: a doubtful run then stays visible in the picture, not lost."""
    out = []
    for seg in segments:
        part = []
        for run in seg["runs"]:
            if span_is_garbled(run["text"], True):
                if part:
                    out.append({"runs": part})
                part = []
            else:
                part.append(run)
        if part:
            out.append({"runs": part})
    return out


def _run_rect(run) -> fitz.Rect:
    return fitz.Rect(run["x0"], run["origin_y"] - run["size"], run["x1"], run["origin_y"] + 0.35 * run["size"])


def _page_content(src, pno: int, ocr_lang: str | None):
    """(background picture, text segments, needs OCR but did not get it)."""
    page = src[pno]
    scan = _layout_page_is_scan(page)
    broken = not scan and page_text_is_broken(page)
    if not (scan or broken):
        segments, rects = _collect_page_text(page)
        bg = _render_without_text(src, pno, rects, LAYOUT_BG_DPI, keep=_rotated_text_rects(page))
        return bg, segments, False
    if ocr_lang is None and broken:
        # Without OCR the readable lines still become text; the garbled ones
        # stay in the picture, where the PDF draws them correctly.
        segments, _ = _collect_page_text(page)
        segments = without_garbled(segments)
        rects = [_run_rect(r) for sg in segments for r in sg["runs"]]
        bg = _render_without_text(src, pno, rects, LAYOUT_BG_DPI, keep=_rotated_text_rects(page))
        return bg, segments, True
    if ocr_lang is None:
        pix = page.get_pixmap(dpi=LAYOUT_BG_DPI, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), [], True
    bg, segments = _ocr_page(src, pno, broken, ocr_lang)
    return bg, segments, False


def _lock(picture) -> None:
    """The background must not move or resize when a click lands on it."""
    c_nv = picture._element.find(f".//{{http://schemas.openxmlformats.org/presentationml/2006/main}}cNvPicPr")
    locks = c_nv.find(f"{{{_A}}}picLocks")
    if locks is None:
        locks = etree.SubElement(c_nv, f"{{{_A}}}picLocks")
    for attr in ("noMove", "noResize", "noRot"):
        locks.set(attr, "1")


def _add_line(slide, runs, ox: int, oy: int, k: float) -> None:
    """One text line as a text box; k = EMU per PDF point on this slide."""
    left, top, width, height = line_box(runs)
    box = slide.shapes.add_textbox(Emu(ox + round(left * k)), Emu(oy + round(top * k)),
                                   Emu(round(width * k)), Emu(round(height * k)))
    tf = box.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    paragraph = tf.paragraphs[0]
    for r in runs:
        run = paragraph.add_run()
        run.text = r["text"]
        font = run.font
        font.size = Pt(round(r["size"] * k / EMU_PER_PT, 1))
        font.bold, font.italic = r["bold"], r["italic"]
        font.name = r["font"]
        font.color.rgb = RGBColor.from_string(r["color"])


def pdf_to_pptx(in_path: str, out_path: str, ocr: bool) -> tuple[list[str], bool]:
    """Writes the presentation. With ``ocr`` scans and damaged text layers are
    recognised; without it Tesseract never runs. Returns (warnings for the
    user, whether OCR produced text)."""
    src = fitz.open(in_path)
    try:
        try:
            repair_pdf_tounicode(src)
        except Exception:
            logger.warning("ToUnicode repair failed; the text layer is used as is", exc_info=True)
        ocr_lang = _tesseract_lang() if ocr else None
        if ocr_lang:
            needs = [p.number for p in src if _layout_page_is_scan(p) or page_text_is_broken(p)]
            ocr_lang = _ocr_lang_order(src, needs, ocr_lang) if needs else ocr_lang
        first = src[0].rect
        prs = Presentation()
        prs.slide_width, prs.slide_height = (Emu(v) for v in slide_size(first.width, first.height))
        blank = prs.slide_layouts[6]
        unread, ocr_ran = 0, False
        for pno in range(src.page_count):
            page = src[pno]
            slide = prs.slides.add_slide(blank)
            ox, oy, w, h = fit_box(page.rect.width, page.rect.height, prs.slide_width, prs.slide_height)
            bg, segments, missed = _page_content(src, pno, ocr_lang)
            unread += missed
            _lock(slide.shapes.add_picture(io.BytesIO(_image_bytes(bg.convert("RGB"))),
                                           Emu(ox), Emu(oy), Emu(w), Emu(h)))
            k = w / page.rect.width
            for seg in segments:
                runs = [r for r in seg["runs"] if r["text"].strip()]
                if runs:
                    _add_line(slide, runs, ox, oy, k)
            ocr_ran |= bool(segments) and (_layout_page_is_scan(page) or page_text_is_broken(page))
        prs.save(out_path)
    finally:
        src.close()
    warning = scan_warning(unread, ocr, ocr_lang is not None)
    return ([warning] if warning else []), ocr_ran
