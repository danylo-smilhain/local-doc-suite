"""PDF -> DOCX in flow mode: pdf2docx, OCR-based flow DOCX, ruled tables, DOCX post-processing."""
import copy
import io
import logging
import os
import re
import shutil
import statistics
import subprocess
import uuid
from typing import List

import fitz
import numpy as np
import pytesseract
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Emu, Pt
from pdf2docx import Converter
from PIL import Image

from app.config import OUTPUT_DIR
from app.ocr import OCR_CONFIG, OCR_DPI, OCR_LANG, page_is_scan, page_needs_ocr
from app.ooxml import WP, V, W

logger = logging.getLogger(__name__)

BG_COVERAGE = 0.65
DPI = 200
INK_THRESH = 200
MIN_INK_PX = 4
MIN_BAND_H_PT = 4.0
MERGE_GAP_PX = 60
MIN_INK_AREA = 80
FORMULA_MAX_CHARS = 28
FORMULA_CENTER_TOL = 90.0
FORMULA_MIN_LEFT = 120.0

USE_OCRMYPDF = True
OCRMYPDF_TIMEOUT = 900


def ocrmypdf_available() -> bool:
    return USE_OCRMYPDF and shutil.which("ocrmypdf") is not None

def ocrmypdf_rebuild(in_path: str, out_path: str, lang: str = OCR_LANG) -> bool:
    cmd = [
        "ocrmypdf", "--force-ocr", "--language", lang,
        "--image-dpi", str(OCR_DPI), "--optimize", "0",
        "--quiet", in_path, out_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=OCRMYPDF_TIMEOUT,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.warning(f"ocrmypdf failed: {e}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _median_or(vals, default):
    return statistics.median(vals) if vals else default

def _px_to_pt(px: float, dpi: int) -> float:
    return px * 72.0 / dpi

def _build_docx_from_pages(pages, out_path: str, default_font_pt: float = 11.0):
    if not pages:
        Document().save(out_path)
        return

    sizes = [l['size'] for p in pages for l in p['lines'] if l.get('size')]
    font_pt = _median_or(sizes, default_font_pt)
    font_pt = max(8.0, min(14.0, round(font_pt * 2) / 2))

    lefts, rights, tops, bottoms = [], [], [], []
    for p in pages:
        if not p['lines']:
            continue
        lefts.append(min(l['x0'] for l in p['lines']))
        rights.append(p['w_pt'] - max(l['x1'] for l in p['lines']))
        tops.append(min(l['top'] for l in p['lines']))
        bottoms.append(p['h_pt'] - max(l['top'] + l['h'] for l in p['lines']))

    ml = max(28.0, _median_or(lefts, 56.0))
    mr = max(20.0, _median_or(rights, 28.0))
    mt = max(28.0, _median_or(tops, 56.0))
    mb = max(28.0, _median_or(bottoms, 56.0))

    word = Document()
    section = word.sections[0]
    section.page_width = Pt(pages[0]['w_pt'])
    section.page_height = Pt(pages[0]['h_pt'])
    section.left_margin = Pt(ml)
    section.right_margin = Pt(mr)
    section.top_margin = Pt(mt)
    section.bottom_margin = Pt(mb)

    normal = word.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(font_pt)
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0

    steps, heights = [], []
    for p in pages:
        ls = p['lines']
        heights.extend(l['h'] for l in ls if l.get('h'))
        for a, b in zip(ls, ls[1:]):
            d = b['top'] - a['top']
            if 0 < d < 60:
                steps.append(d)
    line_h = _median_or(heights, font_pt * 1.15)
    leading = _median_or(steps, line_h * 1.25)
    normal_gap = max(0.0, leading - line_h)

    last = len(pages) - 1
    for idx, p in enumerate(pages):
        content_pt = p['w_pt'] - ml - mr
        right_edge = p['w_pt'] - mr

        page_tables = p.get('tables') or []
        # Строки, попавшие в рамку таблицы, не выводим абзацами — их текст
        # уже разложен по ячейкам.
        def _in_table(line):
            cy = line['top'] + (line.get('h', 0) or 0) / 2.0
            cx = (line['x0'] + line['x1']) / 2.0
            for t in page_tables:
                b = t['bbox']
                if b.y0 - 2 <= cy <= b.y1 + 2 and b.x0 - 2 <= cx <= b.x1 + 2:
                    return True
            return False
        page_lines = [l for l in p['lines'] if not _in_table(l)]

        paras, cur, prev = [], None, None
        for line in page_lines:
            gap = (line['top'] - (prev['top'] + prev['h'])) if prev else 0.0
            if cur is None:
                start_new = True
            else:
                prev_full = prev['x1'] > right_edge - 0.12 * content_pt
                start_new = gap > 0.6 * leading or not prev_full
            if start_new:
                if cur:
                    paras.append(cur)
                cur = {'lines': [line], 'gap_before': gap, 'top': line['top']}
            else:
                cur['lines'].append(line)
            prev = line
        if cur:
            paras.append(cur)

        # Порядок вывода: абзацы и таблицы вперемешку по вертикали.
        blocks = [('para', para['top'], para) for para in paras]
        blocks += [('table', t['bbox'].y0, t) for t in page_tables]
        blocks.sort(key=lambda b: b[1])

        for kind, _y, payload in blocks:
            if kind == 'table':
                _add_word_table(word, payload['rows'])
                continue
            para = payload
            text = " ".join(l['text'] for l in para['lines']).strip()
            if not text:
                continue
            para_obj = word.add_paragraph(text)

            extra = para.get('gap_before', 0.0) - normal_gap
            if extra > 2.0:
                para_obj.paragraph_format.space_before = Pt(min(extra, 24.0))

            para_sizes = [l['size'] for l in para['lines'] if l.get('size')]
            sz = _median_or(para_sizes, font_pt)
            bigger = sz >= font_pt + 1.0
            if abs(sz - font_pt) > 1.5:
                for run in para_obj.runs:
                    run.font.size = Pt(max(8.0, min(20.0, round(sz * 2) / 2)))

            first = para['lines'][0]
            left_gap = first['x0'] - ml
            right_gap = (p['w_pt'] - first['x1']) - mr

            centered = (content_pt > 0 and left_gap > 0.12 * content_pt and
                        abs(left_gap - right_gap) < 0.08 * content_pt)

            if centered:
                para_obj.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif content_pt > 0 and left_gap > 0.35 * content_pt and right_gap < 0.05 * content_pt:
                para_obj.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                para_obj.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                if content_pt > 0 and 4 < left_gap < 0.25 * content_pt:
                    para_obj.paragraph_format.first_line_indent = Pt(left_gap)

            short = len(text) < 90
            upper = short and text == text.upper() and any(c.isalpha() for c in text)
            if bigger or upper or (centered and short):
                for run in para_obj.runs:
                    run.bold = True

        if idx < last:
            word.add_page_break()

    word.save(out_path)

_DOTS_RE = re.compile(r'[.\u00b7\u2022\u2026]{3,}')
_REPEAT_RE = re.compile(r'(\w)\1{3,}', re.UNICODE)

def _clean_ocr_text(text: str) -> str:
    text = _DOTS_RE.sub(' … ', text)
    text = _REPEAT_RE.sub(' … ', text)
    text = re.sub(r'…\s*(?:[а-яa-zіїєґ]{1,6}[:;.,]*\s*)+…', ' … ', text)
    text = re.sub(r'…\s*(?:[а-яa-zіїєґ]{1,6}[:;.,]*\s*)+(?=(?:[IVXLCDM\d]+\s*)?$)', ' … ', text)
    text = re.sub(r'\b(?:нина|нання|мання|ниши|гмо|яя|IM)\b[:;.,]*\s*', '', text, flags=re.IGNORECASE)
    
    tokens = []
    for tok in text.split():
        core = tok.strip('.,;:')
        if (len(core) >= 3 and core.isalpha() and core.islower()
                and len(set(core)) <= 2):
            tokens.append('…')
        else:
            tokens.append(tok)
    text = " ".join(tokens)
    text = re.sub(r'(?:\s*…\s*)+', ' … ', text)
    return re.sub(r'\s{2,}', ' ', text).strip()

def _pdf_page_lines(page):
    size_index = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            size_index.append((line["bbox"], statistics.median([s["size"] for s in spans])))

    def _size_for(bbox):
        x0, y0, x1, y1 = bbox
        best, best_ov = None, 0.0
        for (bx0, by0, bx1, by1), size in size_index:
            ov = min(y1, by1) - max(y0, by0)
            if ov > best_ov and min(x1, bx1) > max(x0, bx0):
                best, best_ov = size, ov
        return best

    groups = {}
    for x0, y0, x1, y1, word, bno, lno, wno in page.get_text("words"):
        if not word.strip():
            continue
        rec = groups.setdefault((bno, lno), {'w': [], 'x0': x0, 'x1': x1,
                                             'top': y0, 'bottom': y1})
        rec['w'].append((wno, word))
        rec['x0'] = min(rec['x0'], x0)
        rec['x1'] = max(rec['x1'], x1)
        rec['top'] = min(rec['top'], y0)
        rec['bottom'] = max(rec['bottom'], y1)

    raw = []
    for key in sorted(groups.keys()):
        rec = groups[key]
        bbox = (rec['x0'], rec['top'], rec['x1'], rec['bottom'])
        h = rec['bottom'] - rec['top']
        raw.append({
            'key': key,
            'text': " ".join(w for _, w in sorted(rec['w'])),
            'x0': rec['x0'], 'x1': rec['x1'],
            'top': rec['top'], 'h': h,
            'size': _size_for(bbox) or (h * 0.92 if h else None),
        })

    raw.sort(key=lambda l: (round(l['top'], 1), l['x0']))
    merged = []
    for line in raw:
        if merged:
            prev = merged[-1]
            ov = min(prev['top'] + prev['h'], line['top'] + line['h']) - \
                 max(prev['top'], line['top'])
            if ov > 0.6 * min(prev['h'] or 1, line['h'] or 1):
                prev['text'] = (prev['text'] + ' ' + line['text']).strip()
                prev['x0'] = min(prev['x0'], line['x0'])
                prev['x1'] = max(prev['x1'], line['x1'])
                prev['h'] = max(prev['h'], line['h'])
                if line.get('size') and (not prev.get('size') or line['size'] > prev['size']):
                    prev['size'] = line['size']
                continue
        merged.append(dict(line))

    for line in merged:
        line['text'] = _clean_ocr_text(line['text'])
    return [l for l in merged if l['text']]


def _cluster(values, gap):
    """Схлопывает близкие координаты (пиксели линий) в одну."""
    if not values:
        return []
    values = sorted(values)
    out = [[values[0]]]
    for v in values[1:]:
        if v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def detect_ruled_tables(page, dpi=DPI):
    """Находит линованные таблицы на странице-скане.

    ocrmypdf кладёт распознанный текст поверх картинки, но рамки таблиц
    остаются пикселями, а не векторами — поэтому find_tables со стратегией
    по линиям их не видит. Здесь линии находим по картинке (проекции тёмных
    пикселей), а текст ячеек берём из OCR-слоя через find_tables(explicit).
    Возвращает список словарей: {'bbox': fitz.Rect, 'rows': [[str, ...], ...]}.
    """
    try:
        import numpy as np
    except Exception:
        logger.debug("Suppressed error in detect_ruled_tables()", exc_info=True)
        return []
    try:
        pm = page.get_pixmap(dpi=dpi)
    except Exception:
        logger.debug("Suppressed error in detect_ruled_tables()", exc_info=True)
        return []
    buf = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)
    g = buf[:, :, 0]
    dark = g < 140
    H, W = dark.shape
    if H == 0 or W == 0:
        return []
    sx = page.rect.width / W
    sy = page.rect.height / H

    # Горизонтальные линии: строки, где тёмное покрывает >50% ширины
    hrows = np.where(dark.sum(1) > 0.5 * W)[0]
    if len(hrows) < 3:
        return []
    hs = _cluster(list(hrows), gap=max(3, int(0.004 * H)))
    if len(hs) < 3:
        return []

    # Рамка таблицы = медиана крайних тёмных пикселей на линиях
    lefts, rights = [], []
    for y in hrows:
        xs = np.where(dark[y])[0]
        if len(xs):
            lefts.append(int(xs.min()))
            rights.append(int(xs.max()))
    if not lefts:
        return []
    left = int(np.median(lefts))
    right = int(np.median(rights))
    if right - left < 0.3 * W:
        return []

    # Вертикальные разделители: столбцы с высоким покрытием в полосе таблицы
    y0, y1 = int(hrows.min()), int(hrows.max())
    band = dark[y0:y1, :]
    span = max(1, y1 - y0)
    cov = band.sum(0) / span
    inner = [x for x in range(left + 10, right - 10) if cov[x] > 0.3]
    verticals = sorted(set(int(v) for v in ([left] + _cluster(inner, gap=8) + [right])))
    if len(verticals) < 3:
        return []

    hlines = [y * sy for y in hs]
    vlines = [x * sx for x in verticals]
    try:
        found = page.find_tables(strategy="explicit",
                                 horizontal_lines=hlines,
                                 vertical_lines=vlines,
                                 snap_tolerance=3)
    except Exception:
        logger.debug("Suppressed error in detect_ruled_tables()", exc_info=True)
        return []

    tables = []
    for tb in getattr(found, "tables", []):
        if tb.col_count < 2 or tb.row_count < 3:
            continue
        rows = []
        for raw in tb.extract():
            cells = [_clean_ocr_text((c or "").replace("\n", " ")) for c in raw]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 3:
            tables.append({"bbox": fitz.Rect(tb.bbox), "rows": rows})
    return tables


def _add_word_table(word, rows):
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    table = word.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    table.autofit = True
    for i, row in enumerate(rows):
        for j in range(ncols):
            cell = table.cell(i, j)
            text = row[j] if j < len(row) else ""
            cell.text = text
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.name = "Times New Roman"
                    if i == 0:
                        run.font.bold = True


def pdf_textlayer_to_docx(pdf_path: str, out_path: str):
    doc = fitz.open(pdf_path)
    pages = []
    try:
        for page in doc:
            try:
                tables = detect_ruled_tables(page)
            except Exception:
                logger.debug("Suppressed error in pdf_textlayer_to_docx()", exc_info=True)
                tables = []
            pages.append({'lines': _pdf_page_lines(page),
                          'tables': tables,
                          'w_pt': page.rect.width, 'h_pt': page.rect.height})
    finally:
        doc.close()
    _build_docx_from_pages(pages, out_path)
    try:
        restore_dstu_bold(out_path)
    except Exception:  # cosmetic post-processing must not fail the conversion
        logger.exception("restore_dstu_bold failed for %s", out_path)


def _ocr_page_lines(img, lang: str):
    data = pytesseract.image_to_data(
        img, lang=lang, config=OCR_CONFIG, output_type=pytesseract.Output.DICT
    )
    lines = {}
    for i in range(len(data['text'])):
        txt = data['text'][i]
        if not txt or not txt.strip():
            continue
        try:
            conf = float(data['conf'][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 30:
            continue
        key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
        left, width = data['left'][i], data['width'][i]
        rec = lines.setdefault(key, {'w': [], 'x0': left, 'x1': left + width,
                                     'top': data['top'][i], 'h': []})
        rec['w'].append(txt.strip())
        rec['x0'] = min(rec['x0'], left)
        rec['x1'] = max(rec['x1'], left + width)
        rec['top'] = min(rec['top'], data['top'][i])
        rec['h'].append(data['height'][i])

    out = []
    for key in sorted(lines.keys()):
        rec = lines[key]
        out.append({
            'key': key,
            'text': " ".join(rec['w']),
            'x0': rec['x0'], 'x1': rec['x1'],
            'top': rec['top'],
            'h': statistics.median(rec['h']) if rec['h'] else 0,
        })
    return out

def pdf_ocr_to_docx(pdf_path: str, out_path: str, lang: str = OCR_LANG, dpi: int = OCR_DPI):
    doc = fitz.open(pdf_path)
    pages = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                raw = _ocr_page_lines(img, lang)
            except Exception:
                logger.debug("Suppressed error in pdf_ocr_to_docx()", exc_info=True)
                raw = []
            sx = page.rect.width / pix.width if pix.width else 1.0
            sy = page.rect.height / pix.height if pix.height else 1.0
            lines = []
            for l in raw:
                h_pt = l['h'] * sy
                lines.append({
                    'key': l['key'][:2],
                    'text': l['text'],
                    'x0': l['x0'] * sx, 'x1': l['x1'] * sx,
                    'top': l['top'] * sy, 'h': h_pt,
                    'size': h_pt / 0.72 if h_pt else None,
                })
            pages.append({'lines': lines,
                          'w_pt': page.rect.width, 'h_pt': page.rect.height})
    finally:
        doc.close()
    _build_docx_from_pages(pages, out_path)


def _segments(page, gap_pt=40.0):
    groups = {}
    for x0, y0, x1, y1, w, b, l, n in page.get_text("words"):
        groups.setdefault((b, l), []).append((x0, y0, x1, y1, w))
    out = []
    for words in groups.values():
        words.sort(key=lambda t: t[0])
        cur = [words[0]]
        for w in words[1:]:
            if w[0] - cur[-1][2] > gap_pt:
                out.append(cur); cur = [w]
            else:
                cur.append(w)
        out.append(cur)
    res = []
    for seg in out:
        rect = fitz.Rect(min(w[0] for w in seg), min(w[1] for w in seg),
                         max(w[2] for w in seg), max(w[3] for w in seg))
        res.append((rect, " ".join(w[4] for w in seg)))
    return res

def _formula_lines(page):
    cx = page.rect.width / 2
    res = []
    for rect, txt in _segments(page):
        t = txt.strip()
        if not t or len(t) > FORMULA_MAX_CHARS:
            continue
        if rect.x0 < FORMULA_MIN_LEFT:
            continue
        if abs((rect.x0 + rect.x1) / 2 - cx) > FORMULA_CENTER_TOL:
            continue
        res.append(rect)
    return res

def find_graphic_bands(page, dpi=DPI):
    zoom = dpi / 72.0
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    ink = arr < INK_THRESH
    skip = _formula_lines(page)
    text_mask = np.zeros_like(ink)
    for x0, y0, x1, y1, *_ in page.get_text("words"):
        if any(fitz.Rect(x0, y0, x1, y1).intersects(s) for s in skip):
            continue
        r0 = max(0, int((y0 - 1.5) * zoom)); r1 = min(pix.height, int((y1 + 1.5) * zoom) + 1)
        c0 = max(0, int((x0 - 1.5) * zoom)); c1 = min(pix.width, int((x1 + 1.5) * zoom) + 1)
        text_mask[r0:r1, c0:c1] = True

    ink_nt = ink & ~text_mask
    candidate = ink_nt.sum(axis=1) > MIN_INK_PX
    wide_text = text_mask.sum(axis=1) > 0.25 * pix.width

    raw, start = [], None
    for i, v in enumerate(candidate):
        if v and start is None:
            start = i
        elif not v and start is not None:
            raw.append([start, i - 1]); start = None
    if start is not None:
        raw.append([start, len(candidate) - 1])

    merged = []
    for band in raw:
        if merged:
            prev = merged[-1]
            if band[0] - prev[1] - 1 <= MERGE_GAP_PX and not wide_text[prev[1] + 1:band[0]].any():
                prev[1] = band[1]; continue
        merged.append(band)

    bands = []
    for r0, r1 in merged:
        if (r1 - r0 + 1) / zoom < MIN_BAND_H_PT:
            continue
        if wide_text[r0:r1 + 1].mean() > 0.3:
            continue
        block = ink_nt[r0:r1 + 1]
        if block.sum() < MIN_INK_AREA:
            continue
        cols = np.where(block.any(axis=0))[0]
        if cols.size == 0:
            continue
        pad = int(2 * zoom)
        c0 = max(0, int(cols[0]) - pad); c1 = min(pix.width, int(cols[-1]) + 1 + pad)
        rect = fitz.Rect(c0 / zoom, r0 / zoom, c1 / zoom, (r1 + 1) / zoom)
        buf = io.BytesIO()
        Image.fromarray(arr[r0:r1 + 1, c0:c1]).save(buf, format="PNG", optimize=True)
        bands.append((rect, buf.getvalue()))
    return bands, skip

def clean_pdf_keep_graphics(in_path, out_path):
    doc = fitz.open(in_path)
    changed = False
    for page in doc:
        if page_is_scan(page):
            continue
        page_area = page.rect.width * page.rect.height
        big = []
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                logger.debug("Suppressed error in clean_pdf_keep_graphics()", exc_info=True)
                continue
            if any(abs(r.width * r.height) >= BG_COVERAGE * page_area for r in rects):
                big.append(xref)
        if not big:
            continue

        bands, formula_lines = find_graphic_bands(page)
        for r in formula_lines:
            page.add_redact_annot(r)
        if formula_lines:
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            except Exception:  # MuPDF error types are not part of its API
                logger.exception("apply_redactions failed on page %s", page.number + 1)

        for xref in big:
            try:
                page.delete_image(xref)
            except Exception:  # MuPDF error types are not part of its API
                logger.exception("delete_image(%s) failed on page %s", xref, page.number + 1)
        for rect, png in bands:
            try:
                page.insert_image(rect, stream=png)
            except Exception:  # MuPDF error types are not part of its API
                logger.exception("insert_image failed on page %s", page.number + 1)
        changed = True

    if not changed:
        doc.close(); return in_path
    doc.save(out_path, garbage=4, deflate=True)
    doc.close()
    return out_path

def strip_background_images_from_docx(docx_path: str):
    try:
        doc = Document(docx_path)
    except Exception:
        logger.debug("Suppressed error in strip_background_images_from_docx()", exc_info=True)
        return

    try:
        section = doc.sections[0]
        page_w = int(section.page_width or Emu(7560000))
        page_h = int(section.page_height or Emu(10692000))
    except Exception:
        logger.debug("Suppressed error in strip_background_images_from_docx()", exc_info=True)
        page_w, page_h = 7560000, 10692000

    max_w, max_h = 0.5 * page_w, 0.5 * page_h

    def kill(node):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)

    body = doc.element.body

    for drawing in list(body.iter(W + 'drawing')):
        anchors = list(drawing.iter(WP + 'anchor'))
        extents = list(drawing.iter(WP + 'extent'))

        if not extents:
            kill(drawing)
            continue

        cx = int(extents[0].get('cx', 0) or 0)
        cy = int(extents[0].get('cy', 0) or 0)

        is_bad = False
        if cx >= max_w or cy >= max_h or anchors:
            is_bad = True

        if is_bad:
            kill(drawing)

    for pict in list(body.iter(W + 'pict')):
        for shape in pict.iter(V + 'shape', V + 'rect', V + 'group', V + 'imagedata'):
            kill(pict)
            break

    try:
        doc.save(docx_path)
    except OSError:
        logger.warning("Could not save post-processed DOCX %s", docx_path, exc_info=True)

def ocr_scanned_pages(pdf_path: str) -> List[str]:
    results = []
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        logger.debug("Suppressed error in ocr_scanned_pages()", exc_info=True)
        return results

    for page in doc:
        if not page_needs_ocr(page):
            continue
        tmp_img = os.path.join(OUTPUT_DIR, f"tmp_ocr_{uuid.uuid4()}.png")
        try:
            page.get_pixmap(dpi=OCR_DPI).save(tmp_img)
            text = pytesseract.image_to_string(Image.open(tmp_img), lang=OCR_LANG,
                                               config=OCR_CONFIG).strip()
            if len(text) > 10:
                results.append(text)
        except Exception:  # render + Tesseract: one bad page must not stop the rest
            logger.exception("OCR of a scanned page failed")
        finally:
            if os.path.exists(tmp_img):
                os.remove(tmp_img)
    doc.close()
    return results

def restore_dstu_bold(docx_path: str):
    num_re = re.compile(r'^(\d+(?:\.\d+)*)(\s+)(.*)$', re.DOTALL)
    try:
        doc = Document(docx_path)
    except Exception:
        logger.debug("Suppressed error in restore_dstu_bold()", exc_info=True)
        return
    for para in doc.paragraphs:
        text = para.text.strip()
        m = num_re.match(text)
        if not m or not para.runs:
            continue
        number, _, rest = m.groups()
        heading = len(text) < 60 and not text.endswith('.')
        if heading:
            for run in para.runs:
                run.bold = True
            continue
        left = len(number)
        for run in para.runs:
            if left <= 0:
                break
            t = run.text
            if len(t.strip()) == 0:
                continue
            if len(t) <= left:
                run.bold = True
                left -= len(t)
            else:
                tail = t[left:]
                run.text = t[:left]
                run.bold = True
                new = copy.deepcopy(run._element)
                run._element.addnext(new)
                from docx.text.run import Run
                nr = Run(new, para)
                nr.text = tail
                nr.bold = False
                left = 0
    try:
        doc.save(docx_path)
    except OSError:
        logger.warning("Could not save post-processed DOCX %s", docx_path, exc_info=True)

def pdf2docx_convert(src_pdf: str, out_path: str, strip_backgrounds: bool = True):
    cv = Converter(src_pdf)
    try:
        cv.convert(out_path, start=0, end=None)
    finally:
        cv.close()
    if strip_backgrounds:
        try:
            strip_background_images_from_docx(out_path)
        except Exception:  # cosmetic post-processing must not fail the conversion
            logger.exception("strip_background_images_from_docx failed for %s", out_path)
    try:
        restore_dstu_bold(out_path)
    except Exception:  # cosmetic post-processing must not fail the conversion
        logger.exception("restore_dstu_bold failed for %s", out_path)
