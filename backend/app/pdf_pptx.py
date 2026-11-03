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
import numpy as np
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Emu, Pt

from app.ocr import (OCR_DPI, OCR_LANG_SAMPLE_PAGES, _choose_ocr_lang_order, _ocr_png, _render_page_png,
                     available_ocr_lang, page_text_is_broken)
from app.pdf_layout import (_FONT_FAMILIES, LAYOUT_BG_DPI, LAYOUT_MIN_FONT_PT, _collect_page_text, _image_bytes, _inpaint_boxes,
                            _layout_page_is_scan, _ocr_line_run, _render_without_text,
                            _rotated_text_rects)
from app.pdf_text import repair_pdf_tounicode
from app.slide_ocr import lines_of, read_slide_words

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
# The page is drawn once more without its pictures over this colour (magenta,
# which slide text does not use) to tell the slide's own letters from text
# inside its photos and screenshots.
UNDERLAY = (1, 0, 1)
# A word box holds letters when this share of its pixels differs by more than
# LETTER_CONTRAST (0-255) from its main colour (letters fill 15-40% of a box).
LETTER_CONTRAST = 60
LETTER_SHARE = 0.05
# Stroke thickness of the letters per font size, where the font does not tell
# its weight. Measured at 132-200 dpi: regular sans 0.065-0.096 (Helvetica,
# DejaVu, the Canva decks), bold sans 0.123-0.19. Serif bold (Times: 0.09-0.12)
# is not told apart and stays regular; regular text is never taken for bold.
BOLD_STROKE_EM = 0.11
# Letters smaller than this many pixels have strokes of a pixel or two, too
# coarse to tell bold from regular; their weight stays as the PDF says.
MIN_WEIGH_PX = 20
# An OCR line with at least this many letters takes its size from its width.
LINE_SIZE_MIN_LETTERS = 4


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


def _ocr_page(page, lang: str, scan: bool) -> PageContent:
    """A scan or a damaged text layer through OCR, at a resolution that suits
    the page size. The page's text layer is not used at all: in a damaged
    Canva export it does not even match the letters drawn (they are vector
    outlines). On a damaged page that is not a scan, words inside its
    photos and screenshots belong to those pictures and are left there.
    Only the pixels of the remaining words are painted over (as Word does
    for scans), so text OCR missed stays visible; with nothing recognised
    the page stays a picture."""
    dpi = ocr_dpi(page.rect.width, page.rect.height)
    full = page.get_pixmap(dpi=dpi, alpha=False)
    full_img = Image.frombytes("RGB", (full.width, full.height), full.samples)
    try:
        words = read_slide_words(full_img, lang)
    except Exception as e:
        logger.warning(f"OCR of page {page.number + 1} failed: {e}")
        words = []
    if not scan and page.get_images(full=True):
        drawn = without_pictures(page, dpi)
        words = [w for w in words if has_letters(drawn, w[:4])]
    runs = (_ocr_line_run(line, 72.0 / dpi) for line in lines_of(words))
    segments = [{"runs": [run]} for run in runs if run]
    if not ocr_found_text(segments):
        return PageContent(full_img, [], False, False)
    return PageContent(_inpaint_boxes(full_img, [w[:4] for w in words]),
                       style_ocr_segments(segments, 72.0 / dpi, full_img), False, True)


def without_pictures(page, dpi: int) -> Image.Image:
    """The page drawn without its raster pictures, over UNDERLAY: letters the
    page draws itself stand out whatever their colour (white ones included),
    where a picture was there is nothing but UNDERLAY."""
    copy = fitz.open()
    copy.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    p = copy[0]
    p.add_redact_annot(p.rect, fill=False)
    p.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                       text=fitz.PDF_REDACT_TEXT_NONE)
    p.draw_rect(p.rect, color=None, fill=UNDERLAY, overlay=False)
    pix = p.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def has_letters(img: Image.Image, box) -> bool:
    """Whether a word box (pixels) holds drawn letters: enough pixels that
    differ clearly from the box's main colour."""
    crop = img.crop(tuple(round(v) for v in box)).convert("RGB")
    pixels = list(crop.getdata())
    if not pixels:
        return False
    main = tuple(sorted(p[i] for p in pixels)[len(pixels) // 2] for i in range(3))
    differ = sum(1 for p in pixels if max(abs(a - b) for a, b in zip(p, main)) > LETTER_CONTRAST)
    return differ >= LETTER_SHARE * len(pixels)


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


def line_size(text: str, size: float, width_pt: float) -> float:
    """The font size of an OCR line on the slide. OCR guesses it from the
    height of the word boxes, which depends on the letters ("покази" has no
    tall ones, a bullet read as "-" is a dash): off by up to a third. A line
    of a few letters gets the size at which it fills its width in the sans
    font the slide uses (Arial; Helvetica's metrics), so it also keeps its
    place; a shorter one keeps OCR's size, shrunk if it is too wide. Never
    below the smallest size the layout writes (PowerPoint refuses < 1 pt)."""
    length = fitz.Font("helv").text_length(text, fontsize=1)
    if sum(c.isalnum() for c in text) >= LINE_SIZE_MIN_LETTERS:
        size = width_pt / length
    else:
        size = min(size, width_pt / length)
    return max(LAYOUT_MIN_FONT_PT, size)


def style_ocr_segments(segments: list[dict], scale_pt: float, img: Image.Image) -> list[dict]:
    """OCR runs come out black Times New Roman; on a slide they take a sans
    font, the colour of their letters in the page picture, bold where the
    letters are thick, and one size for the line that keeps it in its place."""
    for seg in segments:
        runs = []
        for r in seg["runs"]:
            box = (r["x0"] / scale_pt, (r["origin_y"] - 0.9 * r["size"]) / scale_pt,
                   r["x1"] / scale_pt, (r["origin_y"] + 0.25 * r["size"]) / scale_pt)
            r["font"], r["fam"] = _FONT_FAMILIES["sans"][0], "sans"
            r["color"] = text_colour(img.crop(tuple(round(v) for v in box)))
            r["size"] = line_size(r["text"], r["size"], r["x1"] - r["x0"])
            runs += weigh(r, img, 1.0 / scale_pt)
        seg["runs"] = runs
    return segments


def looks_bold(img: Image.Image, box, size_px: float) -> bool:
    """Whether the letters in a box (pixels) are bold: their stroke thickness
    (twice the ink area over its outline) against the font size."""
    a = np.asarray(img.crop(tuple(round(v) for v in box)).convert("RGB")).astype(int)
    if a.size == 0:
        return False
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    dist = np.abs(a - np.median(border, axis=0)).max(axis=2)
    if dist.max() == 0:
        return False
    ink = dist >= 0.5 * dist.max()
    inner = ink.copy()
    inner[1:] &= ink[:-1]
    inner[:-1] &= ink[1:]
    inner[:, 1:] &= ink[:, :-1]
    inner[:, :-1] &= ink[:, 1:]
    outline = int((ink & ~inner).sum())
    return 2 * int(ink.sum()) / max(1, outline) / size_px > BOLD_STROKE_EM


def _word_spans(run: dict) -> list[tuple[float, float, int, int]]:
    """(x0, x1, start, end) of each word of a run: x in points, start and end
    in run["text"]. From the OCR words or the PDF's character boxes; without
    either the run is one word."""
    text, whole = run["text"], [(run["x0"], run["x1"], 0, len(run["text"]))]
    if run.get("words"):
        spans, pos = [], 0
        for x0, x1, word in run["words"]:
            start = text.find(word, pos)
            if start < 0:
                return whole
            spans.append((x0, x1, start, start + len(word)))
            pos = start + len(word)
        return spans or whole
    chars = run.get("chars")
    if not chars or len(chars) != len(text):
        return whole
    spans, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        j = i
        while j < len(text) and not text[j].isspace():
            j += 1
        spans.append((chars[i][0], chars[j - 1][1], i, j))
        i = j
    return spans or whole


def weigh(run: dict, img: Image.Image, k: float) -> list[dict]:
    """A run whose font does not tell its weight, split into runs where its
    words turn bold or regular in the picture (k = pixels per point)."""
    size_px = run["size"] * k
    if size_px < MIN_WEIGH_PX:
        return [run]
    top, bottom = (run["origin_y"] - 0.75 * run["size"]) * k, (run["origin_y"] + 0.05 * run["size"]) * k
    groups: list[list] = []
    for x0, x1, start, _ in _word_spans(run):
        bold = looks_bold(img, (x0 * k - 2, top, x1 * k + 2, bottom), size_px)
        if groups and groups[-1][3] == bold:
            groups[-1][1] = x1
        else:
            groups.append([x0, x1, start, bold])
    parts = []
    for n, (x0, x1, start, bold) in enumerate(groups):
        end = groups[n + 1][2] if n + 1 < len(groups) else len(run["text"])
        part = {key: v for key, v in run.items() if key not in ("chars", "words", "weight_unknown")}
        parts.append(dict(part, text=run["text"][0 if n == 0 else start:end], x0=x0, x1=x1, bold=bold))
    return parts


def _weigh_unknown(segments: list[dict], page) -> list[dict]:
    """Text-layer runs in fonts that do not tell their weight (Canva's
    "Unnamed-T3") take it from the page picture."""
    if not any(r.get("weight_unknown") for seg in segments for r in seg["runs"]):
        return segments
    pix = page.get_pixmap(dpi=LAYOUT_BG_DPI, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    k = LAYOUT_BG_DPI / 72
    return [dict(seg, runs=[p for r in seg["runs"] for p in (weigh(r, img, k) if r.get("weight_unknown") else [r])])
            for seg in segments]


def ocr_dpi(width_pt: float, height_pt: float) -> int:
    """Resolution for OCR of a page this size (see OCR_LONG_SIDE_PX)."""
    return min(OCR_DPI, round(OCR_LONG_SIDE_PX * 72 / max(width_pt, height_pt)))


def ocr_found_text(segments: list[dict]) -> bool:
    words = [w for s in segments for r in s["runs"] for w in r["text"].split()]
    return sum(1 for w in words if sum(c.isalpha() for c in w) >= 3) >= SLIDE_OCR_MIN_WORDS


def _page_content(src, pno: int, ocr_lang: str | None) -> PageContent:
    page = src[pno]
    scan = _layout_page_is_scan(page)
    if not (scan or page_text_is_broken(page)):
        segments, rects = _collect_page_text(page)
        bg = _render_without_text(src, pno, rects, LAYOUT_BG_DPI, keep=_rotated_text_rects(page))
        return PageContent(bg, _weigh_unknown(segments, page), False, False)
    if ocr_lang is not None:
        return _ocr_page(page, ocr_lang, scan)
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
