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
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from app.ocr import (OCR_DPI, OCR_LANG_SAMPLE_PAGES, _choose_ocr_lang_order, _ocr_png, _render_page_png,
                     available_ocr_lang, page_text_is_broken)
from app.pdf_layout import (_FONT_FAMILIES, LAYOUT_BG_DPI, LAYOUT_GFX_CLUSTER_GAP_PT, LAYOUT_MIN_FONT_PT,
                            LAYOUT_SCAN_COVER,
                            _collect_page_text, _find_grid_tables, _image_bytes, _inpaint_boxes,
                            _layout_page_is_scan, _metric_font, _ocr_line_run, _paint_log, _render_without_text,
                            _rotated_text_rects, _text_decorations, _vector_table_primitives, _xy_cut)
from app.pdf_text import repair_pdf_tounicode
from app.slide_ocr import lines_of, read_slide_words
from app.slide_raster import split_picture

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
# OCR works best on letters a few dozen pixels tall: as on an A4 page at
# 300 dpi. A Canva slide is 1440-1920 pt wide; at 300 dpi its titles grow to
# hundreds of pixels and Tesseract misreads them ("РЮ-зах!д" for "PR-захід").
OCR_LONG_SIDE_PX = 3508
# Words of 3+ letters that make OCR output text and not photo noise. Word's
# layout asks for 12 (a document page); a title slide has 3 to 7.
SLIDE_OCR_MIN_WORDS = 3
# A fill covering this share of the page (page colour, card, a side panel of
# half the slide) is part of its backdrop, as is a picture covering it like a
# scan does (a texture); a screenshot over 60% of a slide is not. The backdrop
# is one locked picture.
BACKDROP_SHARE = 0.4
# A picture this opaque is stored without transparency (see _pieces).
OPAQUE_PIECE = 0.9
# Slide pictures are drawn at twice the slide's own resolution: 2880 px across
# a 16:9 slide, more than a projector or a 4K screen shows of it. Word's 200
# dpi (4000 px) made cut-out photos with transparency megabytes each.
SLIDE_DPI = 144
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
# A recognised word is painted out of the slide picture this many times its
# box height beyond its box: the passes' boxes are a few pixels off the
# letters, and the edges left over became scraps of pictures.
WORD_MARGIN = 0.1


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
    """What one slide is made of, bottom to top: a locked background picture
    (None when the page was split into objects), the page's own objects as
    pictures (_split_objects: the backdrop first), and the text lines."""
    background: Image.Image | None
    segments: list[dict]
    unread: bool        # its text needed OCR, which this tool does not run
    recognised: bool    # its text comes from OCR
    objects: list[dict] = []


def _ocr_page(page, lang: str, scan: bool) -> PageContent:
    """A scan or a damaged text layer through OCR, at a resolution that suits
    the page size. The page's text layer is not used at all: in a damaged
    Canva export it does not even match the letters drawn (they are vector
    outlines). On a damaged page that is not a scan, words inside its
    photos and screenshots belong to those pictures and are left there.
    Only the pixels of the remaining words are painted over (as Word does
    for scans), so text OCR missed stays visible; with nothing recognised
    no text is painted over. What is left is split as a drawn slide is: a
    locked backdrop and logos, icons, lines, blocks and photos as pictures
    of their own (slide_raster.split_picture)."""
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
    # a line without a letter or a digit is a drawing OCR took for text (a
    # target read as "©"); it stays in the picture
    lines = [ln for ln in lines_of(words, np.asarray(full_img)) if any(c.isalnum() for w in ln for c in w.text)]
    words = [w for ln in lines for w in ln]
    runs = (_ocr_line_run(line, 72.0 / dpi) for line in lines)
    segments = [{"runs": [run]} for run in runs if run]
    found = ocr_found_text(segments)
    clean = _inpaint_boxes(full_img, [word_ink_box(w) for w in words]) if found else full_img
    segments = style_ocr_segments(segments, 72.0 / dpi, full_img) if found else []
    objects = split_picture(clean, 72.0 / dpi, 72.0 / SLIDE_DPI)
    if objects is None:
        return PageContent(clean, segments, False, found)
    return PageContent(None, segments, False, found, objects)


def word_ink_box(word) -> tuple[float, float, float, float]:
    """The pixels to paint out for a recognised word: its box and a margin
    in proportion to its height, for the letters' edges the box misses."""
    x0, y0, x1, y1 = word[:4]
    m = WORD_MARGIN * (y1 - y0)
    return x0 - m, y0 - m, x1 + m, y1 + m


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


def _touch_point(box: fitz.Rect, avoid: list) -> fitz.Point | None:
    """A point inside box and outside every rect of avoid, on a 9 x 9 grid."""
    for fy in (.5, .1, .9, .3, .7, .2, .8, .4, .6):
        for fx in (.5, .1, .9, .3, .7, .2, .8, .4, .6):
            p = fitz.Point(box.x0 + fx * box.width, box.y0 + fy * box.height)
            if not any(p in a for a in avoid):
                return p
    return None


def _without_backdrop(src, pno: int, under: list, over: list):
    """A copy of the page with every visible object painted up to the
    backdrop removed (each touched by a redaction at a point no later visible
    object covers), or None when that cannot be done exactly. under, over:
    (kind, rect, opacity) in paint order."""
    copy = fitz.open()
    copy.insert_pdf(src, from_page=pno, to_page=pno)
    page = copy[0]
    avoid = [r + (-2, -2, 2, 2) for _, r, a in over if a > 0]
    for images in (False, True):
        targets = [r for kind, r, a in under if a > 0 and (kind == "fill-image") == images]
        for r in targets:
            p = _touch_point(r & page.rect, avoid)
            if p is None:
                return None
            page.add_redact_annot(fitz.Rect(p.x - .1, p.y - .1, p.x + .1, p.y + .1), fill=False)
        if targets:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE if images else fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE if images
                                  else fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=fitz.PDF_REDACT_TEXT_NONE)
    key = lambda kind, r: (kind, tuple(round(v) for v in r))
    left = sorted(key(kind, r) for _, kind, r, a in _paint_log(page) if a > 0)
    if left != sorted(key(kind, r) for kind, r, a in over if a > 0):
        return None
    return copy


def _pieces(rgba: Image.Image, full: Image.Image, scale_pt: float) -> list[dict]:
    """A transparent render cut along empty gaps (pdf_layout._xy_cut, as the
    Word layout cuts its graphics): one picture per piece, in points. A piece
    that is nearly all opaque (a photo or phone with rounded corners) is taken
    from the full page render instead, without transparency: a transparent
    PNG of it was megabytes. Only sparse ones (logos, icons) stay transparent."""
    alpha = np.asarray(rgba)[:, :, 3]
    out = []
    for n, (x0, y0, x1, y1) in enumerate(_xy_cut(alpha > 8, max(1, int(LAYOUT_GFX_CLUSTER_GAP_PT / scale_pt))), 1):
        box = (max(0, x0 - 1), max(0, y0 - 1), min(rgba.width, x1 + 1), min(rgba.height, y1 + 1))
        part = rgba.crop(box)
        if (np.asarray(part)[:, :, 3] > 8).mean() >= OPAQUE_PIECE:
            data = _image_bytes(full.crop(box).convert("RGB"))
        else:
            buf = io.BytesIO()
            part.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
        out.append({"kind": "pic", "img": data, "x": box[0] * scale_pt, "y": box[1] * scale_pt,
                    "w": (box[2] - box[0]) * scale_pt, "h": (box[3] - box[1]) * scale_pt, "name": f"Picture {n}"})
    return out


def _split_objects(src, pno: int, clear: list, keep: list) -> list[dict] | None:
    """The page's objects for the slide, bottom to top. The backdrop (all
    that is painted up to the last object covering half the page or more:
    page colour, texture, card) is one picture with the places of the
    objects above it filled in. Everything above it (photos, screenshots in
    their phone frames, logos, icons, blocks, lines, charts) is drawn on a
    transparent page without the backdrop and the text, and cut along the
    empty gaps between them: one picture each. None: the backdrop cannot be
    taken off exactly; the page stays one background picture."""
    page = src[pno]
    # every span, hidden ones too (a block's frame will not do: the layout
    # trims each frame by 15% top and bottom and a list's first line escaped)
    texts = [fitz.Rect(sp["bbox"]) for b in page.get_text("dict")["blocks"] if b.get("type") == 0
             for line in b["lines"] for sp in line["spans"]]
    paint = _paint_log(page)
    log = [(kind, r, alpha) for _, kind, r, alpha in paint]
    big = [n for n, (_, kind, r, alpha) in enumerate(paint) if alpha > 0
           and abs(r & page.rect) >= (LAYOUT_SCAN_COVER if kind == "fill-image" else BACKDROP_SHARE) * abs(page.rect)]
    under, over = (log[:max(big) + 1], log[max(big) + 1:]) if big else ([], log)
    copy = _without_backdrop(src, pno, under, over)
    if copy is None:
        return None
    try:
        rgba = _render_without_text(copy, 0, texts, SLIDE_DPI, keep=keep, clear=clear, alpha=True)
    finally:
        copy.close()
    full = _render_without_text(src, pno, texts, SLIDE_DPI, keep=keep, clear=clear)
    objects = _pieces(rgba, full, 72.0 / SLIDE_DPI)
    k = SLIDE_DPI / 72
    # Under each object the backdrop is filled in with the colour around it,
    # but only where the object has pixels: a circle on a card's corner must
    # leave the rest of its square as it was.
    filled = _inpaint_boxes(full, [(o["x"] * k, o["y"] * k, (o["x"] + o["w"]) * k, (o["y"] + o["h"]) * k)
                                   for o in objects])
    covered = (np.asarray(rgba)[:, :, 3] > 8)[:, :, None]
    backdrop = Image.fromarray(np.where(covered, np.asarray(filled), np.asarray(full.convert("RGB"))))
    return [{"kind": "pic", "img": _image_bytes(backdrop.convert("RGB")), "x": 0.0, "y": 0.0,
             "w": page.rect.width, "h": page.rect.height, "name": "Background", "backdrop": True}] + objects


def _text_page(src, pno: int) -> PageContent:
    """A page with a real text layer (or none, and no scan under it): text
    boxes over the page's own objects, split as for Word (photos and
    screenshots, logos and icons, blocks and lines), with underlines and
    highlights made text formatting. If the split cannot be done safely the
    page stays one background picture under the text."""
    page = src[pno]
    segments, rects = _collect_page_text(page)
    keep = _rotated_text_rects(page)
    objects, clear = None, []
    if not page.rotation:
        try:
            prims = _vector_table_primitives(page, with_meta=True)
            grid = _find_grid_tables(prims[0], page.rect.width, page.rect.height, allow_single=True, fills=prims[1])
            skip = set().union(*(g["seg_ids"] for g in grid))
            _, clear = _text_decorations(segments, prims[0], prims[1], prims[3], grid, skip)
            objects = _split_objects(src, pno, clear, keep)
        except Exception as e:
            logger.warning(f"Objects of page {pno + 1} not split: {e}")
            segments, rects = _collect_page_text(page)      # undecorated again
            objects, clear = None, []
    segments = _weigh_unknown(segments, page)
    if objects is None:
        bg = _render_without_text(src, pno, rects, SLIDE_DPI, keep=keep, clear=clear)
        return PageContent(bg, segments, False, False)
    return PageContent(None, segments, False, False, objects)


def _page_content(src, pno: int, ocr_lang: str | None) -> PageContent:
    page = src[pno]
    scan = _layout_page_is_scan(page)
    if not (scan or page_text_is_broken(page)):
        return _text_page(src, pno)
    if ocr_lang is not None:
        return _ocr_page(page, ocr_lang, scan)
    # A scan or a damaged text layer without OCR: the page stays as it looks.
    pix = page.get_pixmap(dpi=SLIDE_DPI, alpha=False)
    return PageContent(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), [], True, False)


def _lock(picture) -> None:
    """A background picture must not move or resize when a click lands on it."""
    c_nv = picture._element.find(".//" + qn("p:cNvPicPr"))
    locks = c_nv.find(qn("a:picLocks"))
    if locks is None:
        locks = etree.SubElement(c_nv, qn("a:picLocks"))
    for attr in ("noMove", "noResize", "noRot"):
        locks.set(attr, "1")


def fit_run(text: str, size: float, fam: str, bold: bool, italic: bool, width: float) -> tuple[float, float]:
    """(size, letter spacing) in points that keep a run within the width it
    had in the PDF once its font is replaced (Canva's narrow fonts are
    narrower than Arial: text ran out of its block). Spacing first, down to
    -0.1 em as in Word's layout, then a smaller size; a run that is narrower
    in the substitute stays as it is."""
    font = _metric_font(fam, bold, italic)
    n = len(text)
    measured = font.text_length(text, fontsize=size) if font is not None else 0.0
    if n < 2 or measured <= width or width <= 0:
        return size, 0.0
    if (width - measured) / n >= -0.1 * size:
        return size, (width - measured) / n
    per_pt = measured / size - 0.1 * n            # width of the run per point of size at -0.1 em
    fitted = max(LAYOUT_MIN_FONT_PT, width / per_pt) if per_pt > 0 else LAYOUT_MIN_FONT_PT
    return fitted, -0.1 * fitted


def _add_object(slide, it: dict, ox: int, oy: int, k: float, backdrop: bool) -> None:
    """One picture of the page (see _split_objects) on the slide; the backdrop
    is locked so a click on the slide does not drag it."""
    shape = slide.shapes.add_picture(io.BytesIO(it["img"]), Emu(ox + round(it["x"] * k)), Emu(oy + round(it["y"] * k)),
                                     Emu(max(1, round(it["w"] * k))), Emu(max(1, round(it["h"] * k))))
    shape.name = it["name"]
    if backdrop:
        _lock(shape)


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
        size, spacing = fit_run(r["text"], r["size"], r["fam"], r["bold"], r["italic"], r["x1"] - r["x0"])
        font.size = Pt(round(size * k / EMU_PER_PT, 1))
        if spacing:
            font._rPr.set("spc", str(round(spacing * k / EMU_PER_PT * 100)))   # hundredths of a point
        font.bold, font.italic = r["bold"], r["italic"]
        if r.get("underline"):
            font.underline = True
        if r.get("shade"):
            etree.SubElement(etree.SubElement(font._rPr, qn("a:highlight")), qn("a:srgbClr")).set(
                "val", str(r["shade"]).upper())
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
            bg, segments, missed, recognised, objects = _page_content(src, pno, ocr_lang)
            unread += missed
            ocr_ran |= recognised
            if bg is not None:
                _lock(slide.shapes.add_picture(io.BytesIO(_image_bytes(bg.convert("RGB"))),
                                               Emu(ox), Emu(oy), Emu(w), Emu(h)))
            k = w / page.rect.width
            for it in objects:
                _add_object(slide, it, ox, oy, k, backdrop=it.get("backdrop", False))
            for seg in segments:
                # a run of spaces inside a line stays (an underlined space
                # between two words is a run of its own); blank lines go
                if any(r["text"].strip() for r in seg["runs"]):
                    _add_line(slide, seg["runs"], ox, oy, k)
        prs.save(out_path)
    finally:
        src.close()
    warning = scan_warning(unread, ocr, ocr_lang is not None)
    return ([warning] if warning else []), ocr_ran
