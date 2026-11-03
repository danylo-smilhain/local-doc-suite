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
from typing import NamedTuple

import fitz
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Emu, Pt

from app.ocr import (OCR_DPI, OCR_LANG_SAMPLE_PAGES, _choose_ocr_lang_order, _ocr_png, _render_page_png,
                     available_ocr_lang, page_text_is_broken)
from app.pdf_layout import (_FONT_FAMILIES, LAYOUT_BG_DPI, _collect_page_text, _image_bytes, _inpaint_boxes,
                            _layout_page_is_scan, _ocr_segments, _render_without_text,
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
# OCR works best on letters a few dozen pixels tall: as on an A4 page at
# 300 dpi. A Canva slide is 1440-1920 pt wide; at 300 dpi its titles grow to
# hundreds of pixels and Tesseract misreads them ("РЮ-зах!д" for "PR-захід").
OCR_LONG_SIDE_PX = 3508
# Words of 3+ letters that make OCR output text and not photo noise. Word's
# layout asks for 12 (a document page); a title slide has 3 to 7.
SLIDE_OCR_MIN_WORDS = 3


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


class PageContent(NamedTuple):
    background: Image.Image
    segments: list[dict]
    unread: bool        # its text needed OCR, which this tool does not run
    recognised: bool    # its text comes from OCR


def _ocr_page(page, lang: str) -> PageContent:
    """A scan or a damaged text layer through OCR, at a resolution that suits
    the page size. The page's text layer is not used at all: in a damaged
    Canva export it does not even match the letters drawn (they are vector
    outlines). Only the pixels of recognised words are painted over (as
    Word does for scans), so text OCR missed stays visible; with nothing
    recognised the page stays a picture."""
    dpi = ocr_dpi(page.rect.width, page.rect.height)
    full = page.get_pixmap(dpi=dpi, alpha=False)
    full_img = Image.frombytes("RGB", (full.width, full.height), full.samples)
    try:
        segments, boxes = _ocr_segments(full_img, 72.0 / dpi, lang)
    except Exception as e:
        logger.warning(f"OCR of page {page.number + 1} failed: {e}")
        segments, boxes = [], []
    if not ocr_found_text(segments):
        return PageContent(full_img, [], False, False)
    return PageContent(_inpaint_boxes(full_img, boxes), style_ocr_segments(segments, 72.0 / dpi, full_img),
                       False, True)


def text_colour(img: Image.Image) -> str:
    """Colour of the letters in a crop around a recognised line: the pixels
    farthest from the background (the median of the crop's border)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    border = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for y in range(h) for x in (0, w - 1)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    pixels = list(rgb.getdata())
    dist = [sum((a - b) ** 2 for a, b in zip(p, bg)) for p in pixels]
    far = max(dist)
    if far == 0:
        return "000000"
    ink = [p for p, d in zip(pixels, dist) if d >= 0.6 * far]
    return "".join("%02X" % round(sum(p[i] for p in ink) / len(ink)) for i in range(3))


def fit_size(text: str, size: float, width_pt: float) -> float:
    """OCR guesses the size from letter heights; in the sans font that can
    come out wider than the line was. Shrink it so the line keeps its width."""
    measured = fitz.Font("helv").text_length(text, fontsize=size)
    return size if measured <= width_pt else size * width_pt / measured


def style_ocr_segments(segments: list[dict], scale_pt: float, img: Image.Image) -> list[dict]:
    """OCR runs come out black Times New Roman; on a slide they take a sans
    font, the colour of their letters in the page picture and a size that
    keeps the line within its place."""
    for seg in segments:
        for r in seg["runs"]:
            box = (r["x0"] / scale_pt, (r["origin_y"] - 0.9 * r["size"]) / scale_pt,
                   r["x1"] / scale_pt, (r["origin_y"] + 0.25 * r["size"]) / scale_pt)
            r["font"], r["fam"] = _FONT_FAMILIES["sans"][0], "sans"
            r["color"] = text_colour(img.crop(tuple(round(v) for v in box)))
            r["size"] = fit_size(r["text"], r["size"], r["x1"] - r["x0"])
    return segments


def ocr_dpi(width_pt: float, height_pt: float) -> int:
    """Resolution for OCR of a page this size (see OCR_LONG_SIDE_PX)."""
    return min(OCR_DPI, round(OCR_LONG_SIDE_PX * 72 / max(width_pt, height_pt)))


def ocr_found_text(segments: list[dict]) -> bool:
    words = [w for s in segments for r in s["runs"] for w in r["text"].split()]
    return sum(1 for w in words if sum(c.isalpha() for c in w) >= 3) >= SLIDE_OCR_MIN_WORDS


def _page_content(src, pno: int, ocr_lang: str | None) -> PageContent:
    page = src[pno]
    if not (_layout_page_is_scan(page) or page_text_is_broken(page)):
        segments, rects = _collect_page_text(page)
        bg = _render_without_text(src, pno, rects, LAYOUT_BG_DPI, keep=_rotated_text_rects(page))
        return PageContent(bg, segments, False, False)
    if ocr_lang is not None:
        return _ocr_page(page, ocr_lang)
    # A scan or a damaged text layer without OCR: the page stays as it looks.
    pix = page.get_pixmap(dpi=LAYOUT_BG_DPI, alpha=False)
    return PageContent(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), [], True, False)


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
            bg, segments, missed, recognised = _page_content(src, pno, ocr_lang)
            unread += missed
            ocr_ran |= recognised
            _lock(slide.shapes.add_picture(io.BytesIO(_image_bytes(bg.convert("RGB"))),
                                           Emu(ox), Emu(oy), Emu(w), Emu(h)))
            k = w / page.rect.width
            for seg in segments:
                runs = [r for r in seg["runs"] if r["text"].strip()]
                if runs:
                    _add_line(slide, runs, ox, oy, k)
        prs.save(out_path)
    finally:
        src.close()
    warning = scan_warning(unread, ocr, ocr_lang is not None)
    return ([warning] if warning else []), ocr_ran
