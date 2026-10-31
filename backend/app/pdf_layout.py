"""PDF -> DOCX page for page: background picture plus positioned text frames, tables, decorations."""
import io
import logging
import re
import statistics
import unicodedata

import fitz
import numpy as np
import pytesseract
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import Image

from app.ocr import OCR_CONFIG, OCR_DPI, OCR_LANG, page_text_is_broken
from app.pdf_flow import _cluster

logger = logging.getLogger(__name__)

# ===========================================================================
# PDF -> DOCX С СОХРАНЕНИЕМ ВЁРСТКИ (режим "docx-ocr")
# ===========================================================================
# Почему старый путь (clean_pdf_keep_graphics + pdf2docx) ломал журнальные PDF:
#   1. strip_background_images_from_docx удалял ВСЕ «плавающие» картинки
#      (любой wp:anchor) и все картинки больше половины страницы, а
#      clean_pdf_keep_graphics заранее вырезал из PDF крупные фото. В итоге
#      в DOCX не оставалось ни одного изображения.
#   2. pdf2docx переливает текст потоком: шрифт подменяется, абзацы
#      переносятся иначе, страница «распухает» и переезжает на следующую,
#      а распознанный OCR-текст дописывался в конец отдельной главой.
#      Отсюда 48 страниц вместо 40.
#   3. Косые/лесенкой свёрстанные абзацы (страницы 2 и 4 отчёта) pdf2docx
#      собирает в один абзац с выключкой и чужими отступами — текст
#      перемешивается и «наезжает» сам на себя.
#
# Новый подход: одна страница PDF = одна секция DOCX того же размера.
#   * Фон страницы (фотографии, векторная графика, плашки, линии) —
#     растр страницы БЕЗ текста, положенный за текстом (behindDoc) на весь лист.
#   * Текст — редактируемые надписи (текстовые поля без переноса строк),
#     стоящие ровно там же, где строка стояла в PDF. Ширина строки
#     подгоняется межбуквенным интервалом по метрикам шрифта, поэтому
#     замена шрифта не ломает колонки и строки не наезжают друг на друга.
#   * Повёрнутый текст (подписи к фото под углом) остаётся частью фона.
#   * Страницы-сканы и страницы с битым текстовым слоем распознаются
#     tesseract'ом прямо на месте, без «приложения» в конце документа.

LAYOUT_BG_DPI = 200            # разрешение фонового растра
LAYOUT_BG_JPEG_QUALITY = 85
LAYOUT_MIN_FONT_PT = 3.0       # более мелкий текст оставляем в растре
LAYOUT_SPLIT_GAP_EM = 1.6      # разрыв внутри строки (в кеглях) -> отдельная надпись
LAYOUT_OCR_MIN_WORDS = 12      # меньше осмысленных слов — считаем, что текста нет
LAYOUT_OCR_MIN_CONF = 55
LAYOUT_FIT_WIDTH = True        # подгонять ширину строки под ширину в PDF
# Если шрифт Word шире шрифта PDF (узкие/condensed гарнитуры, например
# AvenirNext Condensed в заголовках отчётов МВФ), строку сжимаем
# масштабом символов (w:w), а не отрицательным межбуквенным интервалом:
# интервал отнимается и у пробелов, и при сильном сжатии слова сливаются
# («GLOBALPROSPECTSANDPOLICIES»). Масштаб сужает буквы и пробелы
# пропорционально — как настоящий узкий шрифт.
LAYOUT_MIN_SCALE = 40          # %, нижний предел сжатия w:w
LAYOUT_MAX_SCALE = 200         # %, верхний предел растяжения w:w
LAYOUT_MAX_EXPAND_EM = 0.15    # растяжение интервалом (в кеглях на символ), дальше — масштабом
# "fallback" — Arial/Times New Roman/Courier New (метрики известны, ширина
#              строк гарантированно совпадает с PDF на любом компьютере);
# "pdf"      — имя шрифта из PDF (если шрифт не установлен, Word подставит
#              свой, и строки могут стать шире/уже).
LAYOUT_FONT_MODE = "fallback"

_EMU_PER_PT = 12700

_NS_DECL = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)

# Шрифт Word, базовый шрифт PyMuPDF с теми же метриками (для подгонки
# ширины) и доля кегля от верха строки до базовой линии.
_FONT_FAMILIES = {
    "sans": ("Arial", {"": "helv", "b": "hebo", "i": "heit", "bi": "hebi"}, 0.905),
    "serif": ("Times New Roman", {"": "tiro", "b": "tibo", "i": "tiit", "bi": "tibi"}, 0.891),
    "mono": ("Courier New", {"": "cour", "b": "cobo", "i": "coit", "bi": "cobi"}, 0.833),
}
_SERIF_HINTS = ("times", "serif", "roman", "georgia", "garamond", "minion", "cambria",
                "baskerville", "bodoni", "palatino", "book antiqua", "petersburg",
                "caslon", "didot", "charter", "merriweather", "playfair", "pt serif")
_MONO_HINTS = ("courier", "mono", "consolas", "menlo", "code")
# Гротески. Проверяются раньше антикв: у части PDF-шрифтов (AvenirNext в
# отчётах МВФ) в дескрипторе выставлен флаг «serif», а в имени бывает
# «Roman» (Avenir-Roman, Helvetica-Roman) — без этого списка заголовки
# уходили в Times New Roman.
_SANS_HINTS = ("sans", "grotesk", "gothic", "avenir", "helvetica", "arial", "futura",
               "frutiger", "myriad", "univers", "gill", "verdana", "tahoma", "segoe",
               "calibri", "roboto", "lato", "franklin", "akzidenz", "trebuchet",
               "optima", "century gothic", "montserrat", "nunito", "raleway",
               "benton", "proxima", "museo sans", "fira sans", "noto sans")
# Короткие имена — только в начале имени шрифта (DINPro, Inter, Lato),
# чтобы «din» не срабатывал внутри Wingdings и т.п.
_SANS_PREFIXES = ("din", "inter", "lato")

_metric_fonts = {}


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _clean_xml_text(text: str) -> str:
    # XML 1.0 не допускает управляющие символы; символы private use
    # (иконочные шрифты) в Word всё равно превратятся в квадратики.
    return "".join(
        c for c in text
        if c == "\t" or (unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs", "Cn"))
    )


def _pdf_font_info(span):
    """(имя шрифта для Word, ключ семейства, bold, italic)."""
    raw = span.get("font", "") or ""
    name = re.sub(r"^[A-Z]{6}[+_]", "", raw)
    low = name.lower()
    flags = span.get("flags", 0)
    bold = bool(flags & 16) or any(k in low for k in ("bold", "black", "heavy", "semibold", "demi"))
    italic = bool(flags & 2) or "italic" in low or "oblique" in low
    if any(h in low for h in _SANS_HINTS) or low.startswith(_SANS_PREFIXES):
        fam = "sans"
    elif any(h in low for h in _MONO_HINTS) or flags & 8:
        fam = "mono"
    elif any(h in low for h in _SERIF_HINTS) or (flags & 4 and "sans" not in low):
        fam = "serif"
    else:
        fam = "sans"
    if LAYOUT_FONT_MODE == "pdf":
        base = re.split(r"[-,]", name)[0]
        base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
        base = re.sub(r"\s*(MT|PS|Std|Pro|LT)$", lambda m: " " + m.group(1), base).strip()
        word_font = base or _FONT_FAMILIES[fam][0]
    else:
        word_font = _FONT_FAMILIES[fam][0]
    return word_font, fam, bold, italic


def _metric_font(fam: str, bold: bool, italic: bool):
    key = ("b" if bold else "") + ("i" if italic else "")
    code = _FONT_FAMILIES[fam][1][key]
    if code not in _metric_fonts:
        try:
            _metric_fonts[code] = fitz.Font(code)
        except Exception:
            logger.debug("Suppressed error in _metric_font()", exc_info=True)
            _metric_fonts[code] = None
    return _metric_fonts[code]


def _fit_width(text, size, fam, bold, italic, target_w):
    """Подгонка ширины строки в шрифте Word под ширину строки в PDF.

    Возвращает (scale_pct, spacing_twips): масштаб символов по ширине (w:w,
    100 — без изменений) и межбуквенный интервал в 1/20 pt (w:spacing).

    * Строка в шрифте Word шире, чем в PDF (узкий шрифт в PDF) — сжимаем
      масштабом. Отрицательный интервал отнимается и у пробелов, поэтому при
      сильном сжатии слова сливаются в одно.
    * Строка уже — сначала немного разрядки (так выглядят выключенные по
      ширине строки), остаток — масштабом.
    """
    if not LAYOUT_FIT_WIDTH or LAYOUT_FONT_MODE != "fallback":
        return 100, 0
    n = len(text)
    if n < 1 or target_w <= 0:
        return 100, 0
    font = _metric_font(fam, bold, italic)
    if font is None:
        return 100, 0
    try:
        measured = font.text_length(text, fontsize=size)
    except Exception:
        logger.debug("Suppressed error in _fit_width()", exc_info=True)
        return 100, 0
    if measured <= 0:
        return 100, 0
    if text.isspace():
        # Пробел-разделитель между кусками строки: растягиваем интервалом
        # ровно до ширины разрыва в PDF (em space, табуляция в колонтитуле).
        per_char = (target_w - measured) / n
        per_char = max(-0.1 * size, min(4.0 * size, per_char))
        return 100, int(round(per_char * 20))
    if n < 2:
        return 100, 0

    ratio = target_w / measured
    if ratio < 1.0:
        scale = max(LAYOUT_MIN_SCALE, int(ratio * 100))   # вниз — остаток всегда >= 0
    else:
        need = (target_w - measured) / n
        limit = LAYOUT_MAX_EXPAND_EM * size
        if need <= limit:
            scale = 100
        else:
            # часть разницы забирает разрядка, остальное — масштаб
            scale = int((target_w - limit * n) / measured * 100)
            scale = max(100, min(LAYOUT_MAX_SCALE, scale))
    scaled = measured * scale / 100.0
    per_char = (target_w - scaled) / n
    per_char = max(-0.1 * size, min(0.6 * size, per_char))
    return scale, int(round(per_char * 20))


def _char_spacing_twips(text, size, fam, bold, italic, target_w):
    """Совместимость: только межбуквенный интервал из _fit_width."""
    return _fit_width(text, size, fam, bold, italic, target_w)[1]


def _rotated_text_rects(page):
    """Рамки повёрнутого текста. Он остаётся в фоновом растре, поэтому
    redaction горизонтального текста не должен его задевать."""
    out = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        logger.debug("Suppressed error in _rotated_text_rects()", exc_info=True)
        return out
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            if abs(dy) > 0.02 or dx <= 0:
                if any(s.get("text", "").strip() for s in line.get("spans", [])):
                    out.append(fitz.Rect(line["bbox"]))
    return out


def _subtract_rects(rect, keep):
    """Наибольший прямоугольный кусок rect, не пересекающийся ни с одним из
    keep. MuPDF удаляет символ при ЛЮБОМ пересечении его рамки с областью
    redaction, поэтому для удаления горизонтального символа достаточно
    куска его рамки, а повёрнутый текст рядом при этом уцелеет."""
    pieces = [fitz.Rect(rect)]
    for k in keep:
        nxt = []
        for p in pieces:
            if not p.intersects(k):
                nxt.append(p)
                continue
            for cand in (fitz.Rect(p.x0, p.y0, min(p.x1, k.x0), p.y1),   # слева
                         fitz.Rect(max(p.x0, k.x1), p.y0, p.x1, p.y1),   # справа
                         fitz.Rect(p.x0, p.y0, p.x1, min(p.y1, k.y0)),   # сверху
                         fitz.Rect(p.x0, max(p.y0, k.y1), p.x1, p.y1)):  # снизу
                if cand.width > 0.5 and cand.height > 0.5:
                    nxt.append(cand)
        if not nxt:
            return None
        pieces = [max(nxt, key=lambda r: r.width * r.height)]
    return pieces[0] if pieces else None


def _line_segments(line):
    """Разбивает строку PDF на куски по большим горизонтальным разрывам
    (колонки таблиц, «пункт ..... страница» в оглавлении)."""
    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
    if not spans:
        return []
    segs, cur = [], [spans[0]]
    for s in spans[1:]:
        gap = s["bbox"][0] - cur[-1]["bbox"][2]
        if gap > LAYOUT_SPLIT_GAP_EM * max(s.get("size", 10), 1):
            segs.append(cur)
            cur = [s]
        else:
            cur.append(s)
    segs.append(cur)
    return segs


def _collect_page_text(page):
    """Горизонтальные строки страницы -> список надписей.
    Возвращает (segments, rects_to_remove)."""
    segments, rects = [], []
    try:
        # rawdict: те же строки и спаны, что и dict, плюс рамка каждого
        # символа — по ним спан режется там, где начинается/кончается
        # подчёркивание или выделение цветом.
        blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
    except Exception:
        logger.debug("Suppressed error in _collect_page_text()", exc_info=True)
        return segments, rects
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                if "chars" in s and "text" not in s:
                    s["text"] = "".join(ch.get("c", "") for ch in s["chars"])
            dx, dy = line.get("dir", (1.0, 0.0))
            if abs(dy) > 0.02 or dx <= 0:
                continue  # повёрнутый текст остаётся в растре
            for seg in _line_segments(line):
                runs = []
                for s in seg:
                    size = float(s.get("size", 0) or 0)
                    if size < LAYOUT_MIN_FONT_PT:
                        continue
                    chars = [(ch.get("c", ""), ch["bbox"][0], ch["bbox"][2])
                             for ch in s.get("chars", []) if _clean_xml_text(ch.get("c", ""))]
                    text = _clean_xml_text(s.get("text", ""))
                    if not text.strip():
                        continue
                    word_font, fam, bold, italic = _pdf_font_info(s)
                    x0, y0, x1, y1 = s["bbox"]
                    run = {
                        "text": text, "size": size, "font": word_font, "fam": fam,
                        "bold": bold, "italic": italic,
                        "color": "%06X" % (int(s.get("color", 0)) & 0xFFFFFF),
                        "x0": x0, "x1": x1, "origin_y": s.get("origin", (x0, y1))[1],
                    }
                    if chars and "".join(c[0] for c in chars) == text:
                        run["chars"] = [(c[1], c[2]) for c in chars]
                    runs.append(run)
                    rects.append(fitz.Rect(s["bbox"]))
                if not runs:
                    continue
                # Ведущие пробелы сдвигают надпись — переносим их в координату.
                first = runs[0]
                stripped = first["text"].lstrip()
                if len(stripped) != len(first["text"]):
                    font = _metric_font(first["fam"], first["bold"], first["italic"])
                    lead = first["text"][:len(first["text"]) - len(stripped)]
                    if first.get("chars"):
                        first["chars"] = first["chars"][len(lead):]
                        first["x0"] = first["chars"][0][0] if first["chars"] else first["x0"]
                    elif font is not None:
                        first["x0"] += font.text_length(lead, fontsize=first["size"])
                    first["text"] = stripped
                runs[-1]["text"] = runs[-1]["text"].rstrip()
                if runs[-1].get("chars"):
                    runs[-1]["chars"] = runs[-1]["chars"][:len(runs[-1]["text"])]
                # Пробельные спаны (em space U+2003, обычный пробел отдельным
                # спаном) выше отброшены, и соседние куски склеивались:
                # «CHAPTER 1GLOBAL PROSPECTS AND POLICIES» в колонтитуле.
                # Возвращаем пробел и отдаём ему ширину разрыва — подгонка
                # ширины растянет его до исходного расстояния.
                spaced = [runs[0]]
                for cur in runs[1:]:
                    prev = spaced[-1]
                    gap = cur["x0"] - prev["x1"]
                    if (gap > 0.15 * min(prev["size"], cur["size"])
                            and not prev["text"][-1:].isspace()
                            and not cur["text"][:1].isspace()):
                        spaced.append(dict(cur, text=" ", x0=prev["x1"], x1=cur["x0"]))
                    spaced.append(cur)
                segments.append({"runs": spaced})
    return segments, rects


def _invisible_text_rects(page):
    """Прямоугольники невидимого текста (OCR-слой поверх скана)."""
    out = []
    try:
        for tr in page.get_texttrace():
            if tr.get("type") == 3 or tr.get("opacity", 1) == 0:
                out.append(fitz.Rect(tr["bbox"]))
    except Exception:  # MuPDF raises several unrelated types; invisible text is optional
        logger.exception("get_texttrace failed; invisible text is not detected on this page")
    return out


def _render_without_text(src_doc, pno, rects, dpi, keep=None, clear=None, alpha=False):
    """Растр страницы без текста: текст вычищается redaction'ом на копии
    страницы, картинки и векторная графика не трогаются.

    keep — рамки текста, который должен остаться в растре (повёрнутые
    надписи). Раньше redaction крупной цифры «1» в шапке главы задевал
    вертикальное слово «CHAPTER» рядом, и оно пропадало из DOCX.

    clear — области таблиц: векторная графика, целиком лежащая в них
    (линии сетки, заливки ячеек), удаляется — её заменяют границы и
    заливка настоящей таблицы Word.

    alpha — прозрачный фон (RGBA) вместо белого: графику страницы режут на
    отдельные рисунки (см. _split_page_graphics)."""
    tmp = fitz.open()
    keep = [fitz.Rect(k) for k in (keep or [])]
    merged = []
    graphics_removed = False
    try:
        tmp.insert_pdf(src_doc, from_page=pno, to_page=pno)
        page = tmp[0]
        for r in rects:
            r = fitz.Rect(r)
            # чуть ужимаем по вертикали, чтобы не задеть соседние повёрнутые подписи
            h = r.height
            r.y0 += 0.15 * h
            r.y1 -= 0.15 * h
            if r.is_empty:
                continue
            if keep:
                r = _subtract_rects(r, keep)
                if r is None or r.is_empty:
                    continue
            page.add_redact_annot(r, fill=False)
        if rects:
            kwargs = {}
            for name, const in (("images", "PDF_REDACT_IMAGE_NONE"),
                                ("graphics", "PDF_REDACT_LINE_ART_NONE")):
                if hasattr(fitz, const):
                    kwargs[name] = getattr(fitz, const)
            try:
                page.apply_redactions(**kwargs)
            except TypeError:
                page.apply_redactions(images=0)
        if clear:
            # Второй проход: только графика таблиц и подчёркиваний. Текст
            # (повёрнутые подписи, оставленные в растре) и картинки не трогаем.
            # Пересекающиеся области объединяем: MuPDF при перекрытии
            # redaction-аннотаций удаляет графику только по одной из них
            # (соседние подчёркивания одной строки оставались в фоне).
            merged = [fitz.Rect(r) for r in clear]
            changed = True
            while changed:
                changed = False
                out = []
                for r in merged:
                    for k, m in enumerate(out):
                        if m.intersects(r) or m.contains(r) or r.contains(m):
                            out[k] = m | r
                            changed = True
                            break
                    else:
                        out.append(r)
                merged = out
            for r in merged:
                page.add_redact_annot(r, fill=False)
            kwargs = {}
            for name, const in (("images", "PDF_REDACT_IMAGE_NONE"),
                                ("graphics", "PDF_REDACT_LINE_ART_REMOVE_IF_COVERED"),
                                ("text", "PDF_REDACT_TEXT_NONE")):
                if hasattr(fitz, const):
                    kwargs[name] = getattr(fitz, const)
            if "graphics" in kwargs:
                try:
                    page.apply_redactions(**kwargs)
                    graphics_removed = True
                except TypeError:
                    kwargs.pop("text", None)
                    try:
                        page.apply_redactions(**kwargs)
                        graphics_removed = True
                    except Exception as e:
                        logger.warning(f"Графику таблиц не удалось убрать из фона: {e}")
        # Неприменённые redaction-аннотации (PyMuPDF без PDF_REDACT_LINE_ART_*
        # или сбой apply_redactions) MuPDF рисует красной рамкой с диагоналями —
        # в DOCX они выглядели как лишние рамки. Удаляем их до растеризации;
        # собственные аннотации PDF (не redaction) остаются в фоне как были.
        for annot in list(page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []):
            page.delete_annot(annot)
        pix = page.get_pixmap(dpi=dpi, alpha=alpha)
        if alpha:
            # samples с прозрачностью у MuPDF premultiplied — через PNG получаем обычный RGBA
            return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if merged and not graphics_removed:
            # PyMuPDF без PDF_REDACT_LINE_ART_* (до 1.24.2) не умеет убирать
            # векторную графику: сетка и заливки таблиц оставались в фоне под
            # настоящей таблицей Word и «вылезали», если картинку сдвинуть.
            # Поэтому области таблиц и подчёркиваний закрашиваем белым прямо в
            # растре (текст из них уже вычищен первым проходом), а встроенные
            # картинки, попавшие в эти области, возвращаем из исходного растра.
            orig = img.copy()
            sx = pix.width / float(page.rect.width)
            sy = pix.height / float(page.rect.height)

            def _px(r):
                return (max(0, int(r.x0 * sx)), max(0, int(r.y0 * sy)),
                        min(pix.width, int(r.x1 * sx + 1)), min(pix.height, int(r.y1 * sy + 1)))

            for r in merged:
                box = _px(r)
                if box[2] > box[0] and box[3] > box[1]:
                    img.paste((255, 255, 255), box)
            try:
                pics = [fitz.Rect(i["bbox"]) for i in page.get_image_info()]
            except Exception:
                logger.debug("Suppressed error in _render_without_text()", exc_info=True)
                pics = []
            for pic in pics:
                for r in merged:
                    part = pic & r
                    if part.is_empty:
                        continue
                    box = _px(part)
                    if box[2] > box[0] and box[3] > box[1]:
                        img.paste(orig.crop(box), box[:2])
        return img
    finally:
        tmp.close()


def _inpaint_boxes(img, boxes_px, pad=2):
    """Закрашивает области текста на растре цветом их окрестности
    (для сканов, где текст — это пиксели)."""
    arr = np.array(img)
    H, W = arr.shape[:2]
    for x0, y0, x1, y1 in boxes_px:
        x0 = max(0, int(x0) - pad); y0 = max(0, int(y0) - pad)
        x1 = min(W, int(x1) + pad); y1 = min(H, int(y1) + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        ring = np.concatenate([
            arr[max(0, y0 - 2):y0, x0:x1].reshape(-1, 3),
            arr[y1:min(H, y1 + 2), x0:x1].reshape(-1, 3),
            arr[y0:y1, max(0, x0 - 2):x0].reshape(-1, 3),
            arr[y0:y1, x1:min(W, x1 + 2)].reshape(-1, 3),
        ])
        color = np.median(ring, axis=0) if len(ring) else np.array([255, 255, 255])
        arr[y0:y1, x0:x1] = color.astype(np.uint8)
    return Image.fromarray(arr)


def _ocr_segments(img, scale_pt, lang):
    """tesseract -> надписи в координатах страницы + пиксельные рамки слов."""
    data = pytesseract.image_to_data(img, lang=lang, config=OCR_CONFIG,
                                     output_type=pytesseract.Output.DICT)
    lines = {}
    for i, txt in enumerate(data["text"]):
        if not txt or not txt.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < LAYOUT_OCR_MIN_CONF:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        l, t, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        lines.setdefault(key, []).append((l, t, l + w, t + h, txt.strip()))
    segments, boxes = [], []
    for key in sorted(lines):
        words = sorted(lines[key])
        boxes.extend(w[:4] for w in words)
        x0 = min(w[0] for w in words); x1 = max(w[2] for w in words)
        bottom = statistics.median([w[3] for w in words])
        h_pt = statistics.median([w[3] - w[1] for w in words]) * scale_pt
        size = max(LAYOUT_MIN_FONT_PT, min(72.0, h_pt / 0.72))
        text = _clean_xml_text(" ".join(w[4] for w in words))
        if not text:
            continue
        segments.append({"par": key[:2], "runs": [{
            "text": text, "size": size, "font": _FONT_FAMILIES["serif"][0], "fam": "serif",
            "bold": False, "italic": False, "color": "000000",
            "x0": x0 * scale_pt, "x1": x1 * scale_pt,
            # базовая линия ~ низ букв без выносных элементов
            "origin_y": bottom * scale_pt - 0.2 * size * 0.72,
            # слова с координатами: строку, пересекающую ячейки таблицы,
            # режем по словам между ячейками
            "words": [(w[0] * scale_pt, w[2] * scale_pt, _clean_xml_text(w[4])) for w in words],
        }]})
    # Высота рамок слов скачет (есть ли в строке выносные элементы), поэтому
    # кегль выравниваем по медиане абзаца — иначе строки абзаца «пляшут».
    by_par = {}
    for s in segments:
        by_par.setdefault(s["par"], []).append(s["runs"][0]["size"])
    for s in segments:
        med = statistics.median(by_par[s["par"]])
        r = s["runs"][0]
        if 0.7 * med <= r["size"] <= 1.4 * med:
            r["size"] = med
    return segments, boxes


def _layout_page_is_scan(page) -> bool:
    try:
        if page.get_text("text").strip():
            return False
        return bool(page.get_images())
    except Exception:
        logger.debug("Suppressed error in _layout_page_is_scan()", exc_info=True)
        return False


def _ocr_is_meaningful(segments) -> bool:
    """Фотография без текста даёт OCR-мусор из пары «слов» — отсекаем."""
    words = [w for s in segments for r in s["runs"] for w in r["text"].split()]
    real = [w for w in words if sum(c.isalpha() for c in w) >= 3]
    return len(real) >= LAYOUT_OCR_MIN_WORDS


def _image_bytes(img):
    """JPEG или PNG — что меньше (белые текстовые страницы в PNG крошечные)."""
    jbuf = io.BytesIO()
    img.save(jbuf, format="JPEG", quality=LAYOUT_BG_JPEG_QUALITY, optimize=True)
    small = img.convert("P", palette=getattr(getattr(Image, "Palette", Image), "ADAPTIVE", 1), colors=256) \
        if len(img.getcolors(4096) or []) <= 256 and img.getcolors(4096) else None
    if small is not None:
        pbuf = io.BytesIO()
        small.save(pbuf, format="PNG", optimize=True)
        if pbuf.tell() < jbuf.tell():
            return pbuf.getvalue()
    return jbuf.getvalue()


def _is_blank(img):
    lo, hi = img.convert("L").getextrema()
    return lo >= 250


def _content_bbox(img, pad=2):
    """Рамка непустого содержимого растра (px) или None."""
    gray = np.asarray(img.convert("L"))
    mask = gray < 250
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return None
    H, W = gray.shape
    return (max(0, int(cols[0]) - pad), max(0, int(rows[0]) - pad),
            min(W, int(cols[-1]) + 1 + pad), min(H, int(rows[-1]) + 1 + pad))


# ---------------------------------------------------------------------------
# РЕДАКТИРУЕМЫЕ ТАБЛИЦЫ В РЕЖИМЕ ВЁРСТКИ
# ---------------------------------------------------------------------------
# Раньше рамки и заливки таблиц попадали в фоновый растр страницы, а текст
# ячеек — в отдельные надписи поверх него. В Word таблица выглядела как
# картинка: ни добавить строку, ни вписать текст в ячейку.
#
# Теперь сетка таблицы ищется по линиям:
#   * текстовый PDF — по векторным линиям/тонким прямоугольникам
#     (get_drawings), в том числе для таблиц, которые find_tables не видит
#     (продолжение таблицы с прошлой страницы, таблица шире листа);
#   * скан — по горизонтальным/вертикальным штрихам на растре страницы.
# Из сетки собираются ячейки (с объединениями по строкам и столбцам), текст
# раскладывается по ячейкам, а в DOCX вставляется настоящая таблица Word,
# «плавающая» (w:tblpPr) ровно на месте исходной. Линии и заливки таблицы
# из фона убираются и переносятся в границы и заливку ячеек.
# Если внутри таблицы есть «сложная» графика (кривые, диаграммы), фон не
# трогаем: таблица ставится без собственных границ и заливки поверх растра,
# но текст в ней всё равно редактируемый.

LAYOUT_EDITABLE_TABLES = True
LAYOUT_TABLE_SNAP_PT = 2.0          # допуск совпадения координат линий
LAYOUT_TABLE_EDGE_COVER = 0.6       # доля края, покрытая линией -> граница есть
LAYOUT_TABLE_MIN_GAP_PT = 2.5       # более узкие строки/столбцы (двойные линии) схлопываем
LAYOUT_TABLE_LINE_MAX_PT = 3.0      # прямоугольник тоньше — это линия, толще — заливка
LAYOUT_TABLE_MAX_SEGMENTS = 6000    # страницы-диаграммы с тысячами штрихов пропускаем
LAYOUT_TABLE_CELL_MAR_PT = 1.5      # поля ячеек слева/справа
LAYOUT_TABLE_ROOM_PT = 2.5          # запас по высоте ячейки (границы + округления Word)
LAYOUT_TABLE_BOX_PAD_PT = 3.0       # поля надписи, в которой стоит таблица
LAYOUT_SINGLE_BOX_MAX_AREA = 0.3    # рамка 1x1 больше этой доли листа — не таблица
LAYOUT_RASTER_LINE_MIN_PT = 28.0    # минимальная длина линии на скане
LAYOUT_RASTER_LINE_MAX_PT = 3.5     # толще — это плашка/фото, а не линия
LAYOUT_RASTER_DARK = 150            # порог «тёмного» пикселя для линий скана


def _rgb_hex(color):
    """Цвет PyMuPDF (кортеж 0..1: серый / RGB / CMYK) -> 'RRGGBB'."""
    if color is None:
        return None
    try:
        c = [float(v) for v in color]
    except TypeError:
        return "%06X" % (int(color) & 0xFFFFFF)
    if len(c) == 1:
        c = c * 3
    elif len(c) == 4:
        k = c[3]
        c = [(1 - c[0]) * (1 - k), (1 - c[1]) * (1 - k), (1 - c[2]) * (1 - k)]
    if len(c) < 3:
        return None
    return "".join("%02X" % max(0, min(255, int(round(v * 255)))) for v in c[:3])


def _seg(o, p, a, b, w=1.0, color="000000"):
    if a > b:
        a, b = b, a
    return {"o": o, "p": float(p), "a": float(a), "b": float(b),
            "w": float(w or 1.0), "color": color or "000000"}


def _vector_table_primitives(page, with_meta=False):
    """Линии, заливки и «сложная» графика страницы.

    Возвращает (segs, fills, others): segs — горизонтальные/вертикальные
    отрезки (в т.ч. тонкие залитые прямоугольники, которыми Google Docs и
    Word рисуют рамки), fills — залитые прямоугольники, others — рамки
    рисунков, которые нельзя выразить границами и заливкой ячеек.
    with_meta=True добавляет четвёртый элемент — {seq: рисунок}: рамка
    рисунка PDF, «простой» ли он и сколько в нём элементов (чтобы удалять
    из фона только рисунки, целиком перенесённые в DOCX)."""
    segs, fills, others, meta = [], [], [], {}
    try:
        drawings = page.get_drawings()
    except Exception:
        logger.debug("Suppressed error in _vector_table_primitives()", exc_info=True)
        return (segs, fills, others, meta) if with_meta else (segs, fills, others)
    for seq, d in enumerate(drawings):
        n_segs, n_fills = len(segs), len(fills)
        dtype = d.get("type") or ""
        sc = _rgb_hex(d.get("color")) if "s" in dtype else None
        fc = _rgb_hex(d.get("fill")) if "f" in dtype else None
        lw = float(d.get("width") or 1.0)
        simple = True
        for it in d.get("items") or []:
            kind = it[0]
            if kind == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.y - p2.y) < 0.6:
                    s = _seg("h", (p1.y + p2.y) / 2, p1.x, p2.x, lw, sc)
                elif abs(p1.x - p2.x) < 0.6:
                    s = _seg("v", (p1.x + p2.x) / 2, p1.y, p2.y, lw, sc)
                else:
                    simple = False
                    continue
                if sc:
                    segs.append(s)
            elif kind in ("re", "qu"):
                if kind == "qu":
                    q = it[1]
                    if not getattr(q, "is_rectangular", False):
                        simple = False
                        continue
                    r = fitz.Rect(q.rect)
                else:
                    r = fitz.Rect(it[1])
                r.normalize()
                if fc:
                    if min(r.width, r.height) <= LAYOUT_TABLE_LINE_MAX_PT and \
                            max(r.width, r.height) >= 3:
                        if r.width >= r.height:
                            segs.append(_seg("h", (r.y0 + r.y1) / 2, r.x0, r.x1, max(r.height, 0.25), fc))
                        else:
                            segs.append(_seg("v", (r.x0 + r.x1) / 2, r.y0, r.y1, max(r.width, 0.25), fc))
                    elif r.width > 0 and r.height > 0:
                        fills.append({"rect": r, "color": fc, "seq": seq})
                if sc:
                    segs += [_seg("h", r.y0, r.x0, r.x1, lw, sc), _seg("h", r.y1, r.x0, r.x1, lw, sc),
                             _seg("v", r.x0, r.y0, r.y1, lw, sc), _seg("v", r.x1, r.y0, r.y1, lw, sc)]
            else:
                simple = False
        if not simple:
            others.append(fitz.Rect(d.get("rect")))
        for sg in segs[n_segs:]:
            sg["seq"] = seq
        meta[seq] = {"rect": fitz.Rect(d.get("rect")), "simple": simple,
                     "n": (len(segs) - n_segs) + (len(fills) - n_fills)}
    return (segs, fills, others, meta) if with_meta else (segs, fills, others)


def _raster_runs(mask, min_len, max_gap=2):
    """Длинные горизонтальные серии тёмных пикселей: [(row, x0, x1)]."""
    out = []
    rows = np.where(mask.sum(axis=1) >= min_len)[0]
    for y in rows:
        row = mask[y]
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.where(d == 1)[0]
        ends = np.where(d == -1)[0]
        if not len(starts):
            continue
        cs, ce = starts[0], ends[0]
        for s, e in zip(starts[1:], ends[1:]):
            if s - ce <= max_gap:
                ce = e
            else:
                if ce - cs >= min_len:
                    out.append((int(y), int(cs), int(ce)))
                cs, ce = s, e
        if ce - cs >= min_len:
            out.append((int(y), int(cs), int(ce)))
    return out


def _group_runs(runs, max_thick):
    """Серии соседних строк пикселей -> линии (pos, a, b, толщина)."""
    runs.sort()
    groups = []
    for y, a, b in runs:
        for g in reversed(groups[-40:]):
            if y - g["y1"] > 1:
                continue
            ov = min(b, g["b"]) - max(a, g["a"])
            if ov > 0.5 * min(b - a, g["b"] - g["a"]):
                g["y1"] = y
                g["ys"].append(y)
                g["a"] = min(g["a"], a)
                g["b"] = max(g["b"], b)
                break
        else:
            groups.append({"y0": y, "y1": y, "ys": [y], "a": a, "b": b})
    out = []
    for g in groups:
        thick = g["y1"] - g["y0"] + 1
        if thick <= max_thick:
            out.append((sum(g["ys"]) / len(g["ys"]), g["a"], g["b"], thick))
    return out


def _raster_table_primitives(img, scale_pt):
    """Линии таблиц на скане. Возвращает (segs в pt, рамки линий в px)."""
    gray = np.asarray(img.convert("L"))
    dark = gray < LAYOUT_RASTER_DARK
    min_len = max(20, int(LAYOUT_RASTER_LINE_MIN_PT / scale_pt))
    max_thick = max(3, int(LAYOUT_RASTER_LINE_MAX_PT / scale_pt))
    segs, boxes = [], []
    for y, a, b, t in _group_runs(_raster_runs(dark, min_len), max_thick):
        segs.append(_seg("h", y * scale_pt, a * scale_pt, b * scale_pt, max(0.25, t * scale_pt)))
        boxes.append((a, y - t / 2.0 - 1, b, y + t / 2.0 + 1))
    for x, a, b, t in _group_runs(_raster_runs(np.ascontiguousarray(dark.T), min_len), max_thick):
        segs.append(_seg("v", x * scale_pt, a * scale_pt, b * scale_pt, max(0.25, t * scale_pt)))
        boxes.append((x - t / 2.0 - 1, a, x + t / 2.0 + 1, b))
    return segs, boxes


def _snap_coords(values, tol, min_gap):
    """Кластеризация координат линий + схлопывание слишком узких промежутков."""
    xs = _cluster(sorted(values), tol)
    out = []
    for x in xs:
        if out and x - out[-1] < min_gap:
            continue
        out.append(x)
    return out


def _cover(segs, o, pos, a, b, tol):
    """Доля отрезка [a, b] на линии pos, покрытая отрезками ориентации o,
    и самый длинный из покрывающих (для толщины и цвета границы)."""
    if b - a <= 0:
        return 0.0, None
    parts, best, best_len = [], None, 0.0
    for s in segs:
        if s["o"] != o or abs(s["p"] - pos) > tol:
            continue
        lo, hi = max(a, s["a"] - tol), min(b, s["b"] + tol)
        if hi > lo:
            parts.append((lo, hi))
            if hi - lo > best_len:
                best, best_len = s, hi - lo
    if not parts:
        return 0.0, None
    parts.sort()
    total, cs, ce = 0.0, parts[0][0], parts[0][1]
    for lo, hi in parts[1:]:
        if lo <= ce:
            ce = max(ce, hi)
        else:
            total += ce - cs
            cs, ce = lo, hi
    total += ce - cs
    return total / (b - a), best


def _find_grid_tables(segs, page_w, page_h, tol=LAYOUT_TABLE_SNAP_PT, allow_single=False,
                      fills=()):
    """Связные сети горизонтальных и вертикальных линий -> таблицы.

    allow_single — оставлять и одиночные рамки (таблица 1x1): рамка вокруг
    заголовка на титульном листе — в Word это таблица из одной ячейки.
    fills — заливки: граница смены цвета на линии сетки тоже разделяет
    ячейки (шапка «Бал» и строка «10» без линии между ними, но разного
    цвета), хотя рамку там не рисуем."""
    hs = [s for s in segs if s["o"] == "h" and s["b"] - s["a"] >= 2]
    vs = [s for s in segs if s["o"] == "v" and s["b"] - s["a"] >= 2]
    if len(hs) < 2 or len(vs) < 2 or len(hs) + len(vs) > LAYOUT_TABLE_MAX_SEGMENTS:
        return []
    nh = len(hs)
    hp = np.array([s["p"] for s in hs]); ha = np.array([s["a"] for s in hs]); hb = np.array([s["b"] for s in hs])
    vp = np.array([s["p"] for s in vs]); va = np.array([s["a"] for s in vs]); vb = np.array([s["b"] for s in vs])
    touch = ((vp[None, :] >= ha[:, None] - tol) & (vp[None, :] <= hb[:, None] + tol) &
             (hp[:, None] >= va[None, :] - tol) & (hp[:, None] <= vb[None, :] + tol))
    parent = list(range(nh + len(vs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(*np.nonzero(touch)):
        ri, rj = find(int(i)), find(nh + int(j))
        if ri != rj:
            parent[ri] = rj
    # Соосные куски одной линии (рамка, нарисованная двумя половинами без
    # разделителя между ними) — тоже одна сеть.
    for base, group in ((0, hs), (nh, vs)):
        order = sorted(range(len(group)), key=lambda k: (group[k]["p"], group[k]["a"]))
        for ii, k in enumerate(order):
            sk = group[k]
            for k2 in order[ii + 1:]:
                s2 = group[k2]
                if s2["p"] - sk["p"] > tol:
                    break
                if s2["a"] <= sk["b"] + tol and sk["a"] <= s2["b"] + tol:
                    ri, rj = find(base + k), find(base + k2)
                    if ri != rj:
                        parent[ri] = rj
    comps = {}
    for i in range(nh + len(vs)):
        comps.setdefault(find(i), []).append(i)

    tables = []
    for members in comps.values():
        ch = [hs[i] for i in members if i < nh]
        cv = [vs[i - nh] for i in members if i >= nh]
        if len(ch) < 2 or len(cv) < 2:
            continue
        # Таблица шире листа (обрезана краем страницы) — режем по листу.
        xs = _snap_coords([min(max(s["p"], 0.0), page_w) for s in cv], tol, LAYOUT_TABLE_MIN_GAP_PT)
        ys = _snap_coords([min(max(s["p"], 0.0), page_h) for s in ch], tol, LAYOUT_TABLE_MIN_GAP_PT)
        # Открытый край: большинство строк уходит дальше крайней вертикали
        # (таблица обрезана краем листа, на скане правой рамки нет) —
        # добавляем столбец до конца строк.
        if xs:
            ends = [min(s["b"], page_w) for s in ch if min(s["b"], page_w) > xs[-1] + 3]
            if len(ends) >= 0.5 * len(ch):
                xs.append(statistics.median(ends))
            starts = [max(s["a"], 0.0) for s in ch if max(s["a"], 0.0) < xs[0] - 3]
            if len(starts) >= 0.5 * len(ch):
                xs.insert(0, statistics.median(starts))
        if len(xs) < 2 or len(ys) < 2:
            continue
        if xs[-1] - xs[0] < 20 or ys[-1] - ys[0] < 8:
            continue
        nr, nc = len(ys) - 1, len(xs) - 1
        allsegs = ch + cv
        vsep = [[_cover(allsegs, "v", xs[k], ys[r], ys[r + 1], tol)[0] >= LAYOUT_TABLE_EDGE_COVER
                 for k in range(nc + 1)] for r in range(nr)]
        hsep = [[_cover(allsegs, "h", ys[k], xs[c], xs[c + 1], tol)[0] >= LAYOUT_TABLE_EDGE_COVER
                 for c in range(nc)] for k in range(nr + 1)]
        # «Мягкие» разделители — края заливок на линиях сетки.
        for f in fills:
            fr = f["rect"]
            if fr.x1 < xs[0] - tol or fr.x0 > xs[-1] + tol or fr.y1 < ys[0] - tol or fr.y0 > ys[-1] + tol:
                continue
            for ey in (fr.y0, fr.y1):
                k = min(range(len(ys)), key=lambda i: abs(ys[i] - ey))
                if 0 < k < nr and abs(ys[k] - ey) <= tol:
                    for c in range(nc):
                        cw = xs[c + 1] - xs[c]
                        if min(xs[c + 1], fr.x1) - max(xs[c], fr.x0) >= 0.6 * cw:
                            hsep[k][c] = True
            for ex in (fr.x0, fr.x1):
                k = min(range(len(xs)), key=lambda i: abs(xs[i] - ex))
                if 0 < k < nc and abs(xs[k] - ex) <= tol:
                    for r in range(nr):
                        rh = ys[r + 1] - ys[r]
                        if min(ys[r + 1], fr.y1) - max(ys[r], fr.y0) >= 0.6 * rh:
                            vsep[r][k] = True
        owner = [[None] * nc for _ in range(nr)]
        cells = []
        for r in range(nr):
            for c in range(nc):
                if owner[r][c] is not None:
                    continue
                c1 = c + 1
                while c1 < nc and not vsep[r][c1] and owner[r][c1] is None:
                    c1 += 1
                r1 = r + 1
                while (r1 < nr
                       and all(not hsep[r1][cc] and owner[r1][cc] is None for cc in range(c, c1))
                       and all(not vsep[r1][k] for k in range(c + 1, c1))):
                    r1 += 1
                cell = {"r0": r, "r1": r1, "c0": c, "c1": c1,
                        "rect": fitz.Rect(xs[c], ys[r], xs[c1], ys[r1]), "runs": [], "rot": []}
                for rr in range(r, r1):
                    for cc in range(c, c1):
                        owner[rr][cc] = cell
                cells.append(cell)
        bordered = [c for c in cells
                    if hsep[c["r0"]][c["c0"]] or vsep[c["r0"]][c["c0"]] or vsep[c["r0"]][c["c1"]]]
        single = len(cells) < 2 or len(bordered) < 2
        if single and not (allow_single and len(cells) >= 1 and bordered):
            continue
        tables.append({"single": single,"xs": xs, "ys": ys, "nr": nr, "nc": nc, "cells": cells, "owner": owner,
                       "segs": allsegs, "seg_ids": {id(s) for s in allsegs},
                       "bbox": fitz.Rect(xs[0], ys[0], xs[-1], ys[-1]),
                       "clipped": max(s["b"] for s in ch) > page_w + 1})
    tables.sort(key=lambda t: (t["bbox"].y0, t["bbox"].x0))
    return tables


def _cell_at(table, x, y, tol=0.5):
    for cell in table["cells"]:
        r = cell["rect"]
        if r.x0 - tol <= x <= r.x1 + tol and r.y0 - tol <= y <= r.y1 + tol:
            return cell
    return None


def _table_for_point(tables, x, y):
    for t in tables:
        b = t["bbox"]
        if b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1:
            return t
    return None


def _detect_vector_tables(page, image_rects=(), prims=None, ignore_fills=frozenset(),
                          text_points=None):
    """Таблицы текстового PDF. Возвращает (tables, прочие h-линии для подчёркиваний).

    prims — результат _vector_table_primitives (чтобы не разбирать
    графику страницы дважды); ignore_fills — id заливок, которые уже
    стали выделением текста (это не заливка ячеек и не «чужая» графика)."""
    segs, fills, others = (prims or _vector_table_primitives(page))[:3]
    fills = [f for f in fills if id(f) not in ignore_fills]
    W, H = page.rect.width, page.rect.height
    tables = _find_grid_tables(segs, W, H, allow_single=text_points is not None, fills=fills)
    # Одиночная рамка становится таблицей, только если в ней есть текст, нет
    # картинок и она не на пол-листа (рамка вокруг всей страницы, фото и т.п.).
    keep = []
    for t in tables:
        if t.get("single"):
            b = t["bbox"]
            if abs(b) > LAYOUT_SINGLE_BOX_MAX_AREA * W * H or \
                    any(fitz.Rect(ir).intersects(b) for ir in image_rects) or \
                    not any(b.contains(fitz.Point(x, y)) for x, y in (text_points or ())):
                continue
        keep.append(t)
    tables = keep
    if not tables:
        return [], []
    used = set()
    for t in tables:
        used |= t["seg_ids"]
        b = t["bbox"]
        # область, из которой графика таблицы удаляется из фона
        clear = fitz.Rect(b.x0 - 3, b.y0 - 3, b.x1 + 3, b.y1 + 3)
        if t["clipped"] or b.x1 >= W - 1:
            clear.x1 = W + 2000
        if b.x0 <= 1:
            clear.x0 = -2000
        t["clear"] = clear
        # «Сложная» графика или заливки, не совпадающие с ячейками, — фон не трогаем.
        clean = not any(clear.contains(o) for o in others)
        cell_fill = {}
        for f in fills:
            fr = f["rect"]
            if not clear.contains(fr):
                continue
            cx, cy = (fr.x0 + fr.x1) / 2, (fr.y0 + fr.y1) / 2
            cell = _cell_at(t, cx, cy)
            if cell is None or fr.width * fr.height < 0.5 * abs(cell["rect"]):
                clean = False
        for cell in t["cells"]:
            r = cell["rect"]
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            best = None
            for f in fills:
                fr = f["rect"]
                if fr.x0 <= cx <= fr.x1 and fr.y0 <= cy <= fr.y1 and \
                        abs(fr) <= 1.5 * abs(b) and (best is None or f["seq"] > best["seq"]):
                    best = f
            if best and best["color"] != "FFFFFF" and \
                    not any(fitz.Rect(ir).intersects(r) for ir in image_rects):
                cell_fill[id(cell)] = best["color"]
        t["clean"] = clean
        for cell in t["cells"]:
            cell["fill"] = cell_fill.get(id(cell)) if clean else None
    loose_h = [s for s in segs if s["o"] == "h" and id(s) not in used]
    return tables, loose_h


# Подчёркивания и выделение цветом в PDF — это не свойство текста, а
# отдельная графика (линия под строкой, прямоугольник под строкой). Раньше
# они оставались в фоновом рисунке: в Word фон был не пустым, его можно было
# случайно схватить и сдвинуть (вместе с подчёркиваниями), а сам рисунок
# висел на странице как элемент вёрстки. Теперь такие линии/прямоугольники
# превращаются в формат символов (w:u, w:shd) и удаляются из фона; если
# больше ничего не осталось, фоновый рисунок не создаётся вовсе.
LAYOUT_NATIVE_DECORATIONS = True


def _run_chars(r):
    """Рамки символов прогона [(x0, x1)] или None (OCR, пробел-вставка)."""
    ch = r.get("chars")
    if ch and len(ch) == len(r.get("text", "")):
        return ch
    return None


def _text_decorations(segments, segs, fills, meta, tables=(), skip_seg_ids=frozenset()):
    """Подчёркивания и выделение цветом -> формат символов.

    Работает посимвольно: линия часто подчёркивает только часть спана PDF
    («Заповніть Таблицю 1. SNW ФАКТ» — подчёркнуто лишь «Таблицю 1. SNW
    ФАКТ»), поэтому прогоны режутся по границам подчёркивания/выделения.
    Меняет segments на месте (прогоны получают "underline"/"shade").
    Возвращает (id заливок-выделений, рамки рисунков PDF, которые целиком
    перенесены в формат текста и должны исчезнуть из фона)."""
    # пробелы-вставки тоже: подчёркнутый пробел — это поле «для подписи»
    runs = [r for sg in segments for r in sg["runs"]
            if r.get("text", "") and r.get("x1", 0) > r.get("x0", 0)]
    marks = {id(r): ([None] * len(r["text"]), [None] * len(r["text"])) for r in runs}
    used = {}
    hl_fills = set()
    new_segments = []

    def covered(r, a, b):
        """Индексы символов r, центр которых в [a, b], и их суммарная ширина."""
        ch = _run_chars(r)
        if ch is None:
            ov = min(r["x1"], b) - max(r["x0"], a)
            if ov >= 0.6 * (r["x1"] - r["x0"]):
                return list(range(len(r["text"]))), ov
            return [], 0.0
        idx = [i for i, (x0, x1) in enumerate(ch) if a - 0.5 <= (x0 + x1) / 2 <= b + 0.5]
        idx_vis = [i for i in idx if not r["text"][i].isspace()] or idx
        width = sum(ch[i][1] - ch[i][0] for i in idx)
        return (idx if idx_vis else []), width

    def mark(seq):
        if seq is not None:
            used[seq] = used.get(seq, 0) + 1

    # --- подчёркивания: тонкая горизонтальная линия у базовой линии строки
    for sg in segs:
        if sg["o"] != "h" or id(sg) in skip_seg_ids:
            continue
        length = sg["b"] - sg["a"]
        if length < 1.5:
            continue
        hits, cover = [], 0.0
        for r in runs:
            size = r["size"]
            if sg["w"] > max(1.6, 0.16 * size):
                continue
            if not (r["origin_y"] - 0.6 <= sg["p"] <= r["origin_y"] + 0.4 * size):
                continue
            if min(r["x1"], sg["b"]) - max(r["x0"], sg["a"]) <= 0:
                continue
            idx, width = covered(r, sg["a"], sg["b"])
            if idx:
                hits.append((r, idx))
                cover += width
        if not hits:
            # Линия под пустым местом строки («підпис ______») — поле для
            # заполнения: делаем его подчёркнутыми пробелами.
            if sg["w"] <= 1.6 and length <= 250:
                near = [r for r in runs if r["text"].strip()
                        and r["origin_y"] - 0.6 <= sg["p"] <= r["origin_y"] + 0.4 * r["size"]
                        and min(abs(r["x0"] - sg["b"]), abs(sg["a"] - r["x1"])) <= 2 * r["size"]]
                if near:
                    ref = min(near, key=lambda r: min(abs(r["x0"] - sg["b"]), abs(sg["a"] - r["x1"])))
                    n_sp = max(1, int(length / (0.25 * ref["size"])))
                    blank = dict(ref, text=" " * n_sp, x0=sg["a"], x1=sg["b"],
                                 underline=sg["color"] or "auto", shade=None)
                    blank.pop("chars", None)
                    blank.pop("space_before", None)
                    new_segments.append({"runs": [blank]})
                    mark(sg.get("seq"))
            continue
        if cover < 0.6 * length:
            continue          # линия заметно длиннее текста — это не подчёркивание
        for r, idx in hits:
            for i in idx:
                marks[id(r)][0][i] = sg["color"] or "auto"
        mark(sg.get("seq"))

    # --- выделение цветом: залитый прямоугольник высотой со строку под текстом
    for f in fills:
        fr, color = f["rect"], f["color"]
        if not color or color == "FFFFFF":
            continue
        cx, cy = (fr.x0 + fr.x1) / 2, (fr.y0 + fr.y1) / 2
        if any(_cell_at(t, cx, cy) is not None and
               abs(fr) >= 0.5 * abs(_cell_at(t, cx, cy)["rect"]) for t in tables):
            continue          # это заливка ячейки, а не выделение текста
        hits, cover = [], 0.0
        for r in runs:
            size = r["size"]
            if fr.height > 2.6 * size:
                continue
            top, bot = r["origin_y"] - 0.95 * size, r["origin_y"] + 0.3 * size
            if min(bot, fr.y1) - max(top, fr.y0) < 0.5 * (bot - top):
                continue
            idx, width = covered(r, fr.x0, fr.x1)
            if idx:
                hits.append((r, idx))
                cover += width
        if not hits or cover < 0.6 * fr.width:
            continue
        for r, idx in hits:
            for i in idx:
                marks[id(r)][1][i] = color
        hl_fills.add(id(f))
        mark(f.get("seq"))

    # --- резка прогонов по границам формата
    for sg in segments:
        out = []
        for r in sg["runs"]:
            m = marks.get(id(r))
            if not m or not any(m[0]) and not any(m[1]):
                out.append(r)
                continue
            keys = list(zip(m[0], m[1]))
            ch = _run_chars(r)
            if ch is None or len(set(keys)) == 1:
                ul = next((k for k in m[0] if k), None)
                sh = next((k for k in m[1] if k), None)
                out.append(dict(r, underline=ul, shade=sh))
                continue
            start = 0
            for i in range(1, len(keys) + 1):
                if i == len(keys) or keys[i] != keys[start]:
                    piece = dict(r, text=r["text"][start:i], chars=ch[start:i],
                                 x0=ch[start][0], x1=ch[i - 1][1],
                                 underline=keys[start][0], shade=keys[start][1])
                    out.append(piece)
                    start = i
        sg["runs"] = out
    segments.extend(new_segments)

    remove = []
    for seq, cnt in used.items():
        m = meta.get(seq)
        if m and m["simple"] and cnt >= m["n"]:
            r = fitz.Rect(m["rect"])
            remove.append(fitz.Rect(r.x0 - 0.75, r.y0 - 0.75, r.x1 + 0.75, r.y1 + 0.75))
    return hl_fills, remove


def _detect_raster_tables(img, scale_pt, page_w, page_h, ocr_boxes=()):
    """Таблицы скана. Возвращает (tables, рамки линий в px для затирания фона).

    ocr_boxes — рамки распознанных слов (px). Если в ячейке остались
    нераспознанные знаки, заливку ей не ставим: непрозрачная заливка Word
    закрыла бы их, а так они видны с фонового растра."""
    segs, boxes = _raster_table_primitives(img, scale_pt)
    tables = _find_grid_tables(segs, page_w, page_h, tol=max(LAYOUT_TABLE_SNAP_PT, 2.5))
    if not tables:
        return [], []
    arr = np.asarray(img.convert("RGB"))
    paper = np.median(arr.reshape(-1, 3)[::97], axis=0)
    dark = arr.min(axis=2) < LAYOUT_RASTER_DARK
    known = np.zeros(dark.shape, dtype=bool)
    for (x0, y0, x1, y1) in list(ocr_boxes) + list(boxes):
        known[max(0, int(y0) - 3):max(0, int(y1) + 3), max(0, int(x0) - 3):max(0, int(x1) + 3)] = True
    used_boxes = []
    for t in tables:
        b = t["bbox"]
        t["clean"] = True
        t["clear"] = None
        for (x0, y0, x1, y1) in boxes:
            if b.x0 - 3 <= x0 * scale_pt and x1 * scale_pt <= b.x1 + 3 and \
                    b.y0 - 3 <= y0 * scale_pt and y1 * scale_pt <= b.y1 + 3:
                used_boxes.append((x0, y0, x1, y1))
        for cell in t["cells"]:
            r = cell["rect"]
            x0, y0 = int(r.x0 / scale_pt) + 4, int(r.y0 / scale_pt) + 4
            x1, y1 = int(r.x1 / scale_pt) - 4, int(r.y1 / scale_pt) - 4
            cell["fill"] = None
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            px = arr[y0:y1, x0:x1].reshape(-1, 3)
            light = px[px.min(axis=1) > LAYOUT_RASTER_DARK]
            if len(light) < 0.3 * len(px):
                continue
            med = np.median(light, axis=0)
            stray = int((dark[y0:y1, x0:x1] & ~known[y0:y1, x0:x1]).sum())
            if stray > max(25, 0.002 * (x1 - x0) * (y1 - y0)):
                continue
            if np.abs(med - paper).max() > 30:
                cell["fill"] = "%02X%02X%02X" % tuple(int(v) for v in med)
    return tables, used_boxes


def _rotated_lines(page):
    """Повёрнутые строки текстового слоя (для ячеек с вертикальным текстом)."""
    out = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        logger.debug("Suppressed error in _rotated_lines()", exc_info=True)
        return out
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            if not (abs(dy) > 0.02 or dx <= 0):
                continue
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            word_font, fam, bold, italic = _pdf_font_info(spans[0])
            out.append({
                "rect": fitz.Rect(line["bbox"]), "dir": "btLr" if dy < 0 else "tbRl",
                "text": _clean_xml_text("".join(s.get("text", "") for s in spans)).strip(),
                "size": float(spans[0].get("size", 10) or 10), "font": word_font, "fam": fam,
                "bold": bold, "italic": italic,
                "color": "%06X" % (int(spans[0].get("color", 0)) & 0xFFFFFF),
            })
    return out


def _split_run_by_cells(run, table):
    """OCR-строка может пересекать несколько ячеек — режем по словам."""
    words = run.get("words")
    if not words:
        return [run]
    parts, cur, cur_cell = [], [], None
    cy = run["origin_y"] - 0.3 * run["size"]
    for w in words:
        cell = _cell_at(table, (w[0] + w[1]) / 2, cy)
        if cur and cell is not cur_cell:
            parts.append(cur)
            cur = []
        cur.append(w)
        cur_cell = cell
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        out.append(dict(run, text=" ".join(w[2] for w in p), x0=p[0][0], x1=p[-1][1], words=p))
    return out


def _distribute_table_text(tables, segments, rotated=()):
    """Переносит текст, попавший в таблицы, в ячейки. Возвращает оставшиеся надписи."""
    rest = []
    for seg in segments:
        keep = []
        for run in seg["runs"]:
            pieces = [run]
            cy = run["origin_y"] - 0.3 * run["size"]
            t = _table_for_point(tables, (run["x0"] + run["x1"]) / 2, cy)
            if t is None and run.get("words"):
                t = _table_for_point(tables, run["words"][0][0], cy) or \
                    _table_for_point(tables, run["words"][-1][1], cy)
            if t is not None and run.get("words"):
                pieces = _split_run_by_cells(run, t)
            for piece in pieces:
                cx = (piece["x0"] + piece["x1"]) / 2
                tt = _table_for_point(tables, cx, cy)
                cell = _cell_at(tt, cx, cy) if tt else None
                if cell is None:
                    keep.append(piece)
                elif piece["text"].strip():
                    cell["runs"].append(piece)
        while keep and not keep[0]["text"].strip():
            keep.pop(0)
        while keep and not keep[-1]["text"].strip():
            keep.pop()
        if keep:
            rest.append(dict(seg, runs=keep))
    for rl in rotated:
        r = rl["rect"]
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        t = _table_for_point(tables, cx, cy)
        cell = _cell_at(t, cx, cy) if t else None
        if cell is not None and rl["text"]:
            cell["rot"].append(rl)
    return rest


def _tw(pt):
    return int(round(pt * 20))


def _u_xml(underline):
    """w:u для флага подчёркивания (True или цвет линии 'RRGGBB')."""
    if not underline:
        return ""
    if isinstance(underline, str) and re.fullmatch(r"[0-9A-Fa-f]{6}", underline):
        return f'<w:u w:val="single" w:color="{underline.upper()}"/>'
    return '<w:u w:val="single"/>'


def _shd_xml(shade):
    if shade and re.fullmatch(r"[0-9A-Fa-f]{6}", str(shade)):
        return f'<w:shd w:val="clear" w:color="auto" w:fill="{str(shade).upper()}"/>'
    return ""


def _run_xml(r, size_hp, scale=100, underline=False):
    f = _xml_escape(r["font"])
    # noProof: красные/синие волнистые линии проверки орфографии на
    # распознанном тексте только мешают (так же сделано в надписях).
    rpr = (f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>'
           + ("<w:b/><w:bCs/>" if r.get("bold") else "")
           + ("<w:i/><w:iCs/>" if r.get("italic") else "")
           + "<w:noProof/>"
           + f'<w:color w:val="{r.get("color", "000000")}"/>'
           + (f'<w:w w:val="{scale}"/>' if scale != 100 else "")
           + f'<w:sz w:val="{size_hp}"/><w:szCs w:val="{size_hp}"/>'
           + _u_xml(underline or r.get("underline"))
           + _shd_xml(r.get("shade")))
    return rpr


def _mark_rpr(font, size_hp, bold=False):
    f = _xml_escape(font)
    return (f'<w:rPr><w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>'
            + ("<w:b/><w:bCs/>" if bold else "")
            + f'<w:sz w:val="{size_hp}"/><w:szCs w:val="{size_hp}"/></w:rPr>')


def _is_underlined(run, loose_h):
    w = run["x1"] - run["x0"]
    if w <= 0:
        return False
    base, size = run["origin_y"], run["size"]
    for s in loose_h:
        if base - 0.6 <= s["p"] <= base + 0.35 * size:
            ov = min(run["x1"], s["b"]) - max(run["x0"], s["a"])
            if ov >= 0.6 * w:
                return True
    return False


def _line_width_pt(line_runs, size_pt):
    total = 0.0
    for i, r in enumerate(line_runs):
        font = _metric_font(r["fam"], r["bold"], r["italic"])
        txt = (" " if r.get("space_before") else "") + r["text"]
        try:
            total += font.text_length(txt, fontsize=size_pt[i]) if font else 0.5 * size_pt[i] * len(txt)
        except Exception:
            logger.debug("Suppressed error in _line_width_pt()", exc_info=True)
            total += 0.5 * size_pt[i] * len(txt)
    return total


def _cell_body_xml(cell, ctx):
    """Абзацы ячейки + vAlign + направление текста."""
    rect = cell["rect"]
    mar = LAYOUT_TABLE_CELL_MAR_PT
    cell_h = rect.height
    def_font, def_hp = ctx["font"], ctx["size_hp"]

    if cell["rot"]:
        rl = sorted(cell["rot"], key=lambda x: x["rect"].x0)
        runs = []
        for i, x in enumerate(rl):
            hp = max(2, int(round(x["size"] * 2)))
            br = "<w:br/>" if i else ""
            runs.append(f'<w:r><w:rPr>{_run_xml(x, hp)}</w:rPr>{br}'
                        f'<w:t xml:space="preserve">{_xml_escape(x["text"])}</w:t></w:r>')
        hp0 = max(2, int(round(rl[0]["size"] * 2)))
        p = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
             f'<w:jc w:val="center"/>{_mark_rpr(rl[0]["font"], hp0, rl[0]["bold"])}</w:pPr>'
             f'{"".join(runs)}</w:p>')
        return p, "center", rl[0]["dir"]

    runs = sorted((r for r in cell["runs"] if r["text"].strip()),
                  key=lambda r: (r["origin_y"], r["x0"]))
    if not runs:
        # высота строки с запасом на толщину границ, чтобы пустая ячейка
        # не раздвигала строку таблицы
        line_pt = max(1.0, min(def_hp / 2.0 * 1.15, cell_h - LAYOUT_TABLE_ROOM_PT))
        p = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{max(20, _tw(line_pt))}" '
             f'w:lineRule="exact"/>{_mark_rpr(def_font, def_hp)}</w:pPr></w:p>')
        return p, "top", None

    # строки ячейки
    lines = []
    for r in runs:
        r = dict(r, text=r["text"].strip() if len(cell["runs"]) == 1 else r["text"])
        if lines and abs(r["origin_y"] - lines[-1]["base"]) <= 0.45 * max(r["size"], lines[-1]["size"]):
            lines[-1]["runs"].append(r)
            lines[-1]["size"] = max(lines[-1]["size"], r["size"])
        else:
            lines.append({"base": r["origin_y"], "size": r["size"], "runs": [r]})
    for ln in lines:
        ln["runs"].sort(key=lambda r: r["x0"])
        cleaned = []
        for r in ln["runs"]:
            txt = r["text"]
            if not cleaned:
                txt = txt.lstrip()
            r = dict(r, text=txt)
            if cleaned:
                prev = cleaned[-1]
                gap = r["x0"] - prev["x1"]
                if gap > 0.15 * min(r["size"], prev["size"]) and \
                        not prev["text"][-1:].isspace() and not txt[:1].isspace():
                    r["space_before"] = True
            cleaned.append(r)
        if cleaned:
            cleaned[-1]["text"] = cleaned[-1]["text"].rstrip()
        ln["runs"] = [r for r in cleaned if r["text"] or r.get("space_before")]
        ln["x0"] = min(r["x0"] for r in ln["runs"])
        ln["x1"] = max(r["x1"] for r in ln["runs"])
    lines = [ln for ln in lines if ln["runs"]]
    if not lines:
        return _cell_body_xml(dict(cell, runs=[]), ctx)
    # Кегль не может быть больше, чем позволяет высота ячейки: OCR иногда
    # ошибается в размере (строчные буквы с выносными элементами), и
    # раздутая строка раздвигала таблицу, сдвигая её относительно фона.
    cap = max(2.0, (cell_h - LAYOUT_TABLE_ROOM_PT) / (len(lines) * 1.05))
    for ln in lines:
        if ln["size"] > cap:
            k = cap / ln["size"]
            ln["runs"] = [dict(r, size=max(2.0, r["size"] * k)) for r in ln["runs"]]
            ln["size"] = cap

    pitches = [b["base"] - a["base"] for a, b in zip(lines, lines[1:])
               if 0 < b["base"] - a["base"] < 2.5 * max(a["size"], b["size"])]
    size_med = statistics.median([ln["size"] for ln in lines])
    pitch = statistics.median(pitches) if pitches else size_med * 1.15
    pitch = max(pitch, size_med * 1.02)
    # Строки текста + границы должны уместиться в высоту ячейки PDF,
    # иначе Word раздвинет строку таблицы и она наедет на текст ниже.
    room = cell_h - LAYOUT_TABLE_ROOM_PT
    if len(lines) * pitch > room:
        pitch = max(size_med * 1.0, room / len(lines))

    paras = [[lines[0]]]
    for a, b in zip(lines, lines[1:]):
        if b["base"] - a["base"] > 1.6 * pitch:
            paras.append([b])
        else:
            paras[-1].append(b)

    asc_off = lambda size: pitch - 0.22 * size     # от верха строки Word до базовой линии
    top = lines[0]["base"] - asc_off(lines[0]["size"])
    bottom = lines[-1]["base"] + 0.22 * lines[-1]["size"]
    content_h = bottom - top
    top_gap, bot_gap = top - rect.y0, rect.y1 - bottom
    if abs(top_gap - bot_gap) <= max(2.0, 0.2 * cell_h):
        valign, first_before = "center", 0.0
    elif bot_gap < top_gap:
        valign, first_before = "bottom", 0.0
    else:
        valign, first_before = "top", max(0.0, top_gap - 0.5)
    first_before = max(0.0, min(first_before, cell_h - content_h - LAYOUT_TABLE_ROOM_PT))

    out = []
    prev_base = None
    for pi, para in enumerate(paras):
        L = [ln["x0"] - rect.x0 for ln in para]
        R = [rect.x1 - ln["x1"] for ln in para]
        C = [(ln["x0"] + ln["x1"]) / 2 for ln in para]
        cw = rect.width
        tol_c = max(2.5, 0.08 * cw)
        if len(para) == 1:
            if abs(L[0] - R[0]) <= tol_c and L[0] > mar + 0.5:
                jc = "center"
            elif R[0] < L[0] and R[0] < 0.25 * cw:
                jc = "right"
            else:
                jc = "left"
        else:
            if max(C) - min(C) <= 2.5 and (max(L) - min(L) > 2.5 or abs(statistics.mean(L) - statistics.mean(R)) <= tol_c):
                jc = "center"
            elif max(L) - min(L) <= 2.5:
                jc = "left"
            elif max(R) - min(R) <= 2.5:
                jc = "right"
            else:
                jc = "left"
        ind_l = max(0.0, min(L) - mar) if jc == "left" else 0.0
        ind_r = max(0.0, min(R) - mar) if jc == "right" else 0.0
        avail = max(4.0, cw - 2 * mar - ind_l - ind_r)

        before = first_before if pi == 0 else max(0.0, para[0]["base"] - prev_base - pitch)
        prev_base = para[-1]["base"]

        runs_xml = []
        for li, ln in enumerate(para):
            sizes_hp = [max(2, int(round(r["size"] * 2))) for r in ln["runs"]]
            measured = _line_width_pt(ln["runs"], [h / 2.0 for h in sizes_hp])
            scale = 100
            if measured > avail * 0.98 and measured > 0:
                scale = max(LAYOUT_MIN_SCALE, int(avail * 0.97 / measured * 100))
            for ri, r in enumerate(ln["runs"]):
                br = "<w:br/>" if (li and ri == 0) else ""
                txt = (" " if r.get("space_before") else "") + r["text"]
                ul = r.get("underline") or _is_underlined(r, ctx["loose_h"])
                runs_xml.append(f'<w:r><w:rPr>{_run_xml(r, sizes_hp[ri], scale, ul)}</w:rPr>{br}'
                                f'<w:t xml:space="preserve">{_xml_escape(txt)}</w:t></w:r>')
        r0 = para[0]["runs"][0]
        out.append(
            f'<w:p><w:pPr><w:spacing w:before="{_tw(before)}" w:after="0" '
            f'w:line="{max(20, _tw(pitch))}" w:lineRule="exact"/>'
            f'<w:ind w:left="{_tw(ind_l)}" w:right="{_tw(ind_r)}" w:firstLine="0"/>'
            f'<w:jc w:val="{jc}"/>{_mark_rpr(r0["font"], max(2, int(round(r0["size"] * 2))), r0["bold"])}'
            f'</w:pPr>{"".join(runs_xml)}</w:p>')
    return "".join(out), valign, None


def _border(tag, info):
    if not info:
        return f'<w:{tag} w:val="nil"/>'
    sz = max(2, min(96, int(round(info["w"] * 8))))
    return f'<w:{tag} w:val="single" w:sz="{sz}" w:space="0" w:color="{info["color"]}"/>'


def _table_xml(t, loose_h=()):
    """Таблица Word на месте таблицы PDF.

    Возвращает (xml, geom). Таблица не «плавающая» (w:tblpPr): её ставит на
    место надпись-контейнер (см. _DocxLayoutWriter.add_table_box), geom —
    толщины внешних границ для расчёта положения контейнера.

    Высоты строк. Word рисует горизонтальные границы СВЕРХ заданной высоты
    строки (LibreOffice — внутри неё): в Word каждая строка таблицы с
    линиями 1 pt выходила на 1 pt выше, чем в PDF, и таблица на 30 строк
    вырастала на 30 pt, наезжая на текст под ней (стр. 6–8). Поэтому из
    высоты строки вычитается толщина её границ (половина верхней и
    половина нижней — общие границы делят соседние строки)."""
    xs, ys, nr, nc = t["xs"], t["ys"], t["nr"], t["nc"]
    segs, tol = t["segs"], LAYOUT_TABLE_SNAP_PT
    styled = t.get("clean", True)
    xtw = [_tw(x) for x in xs]
    ytw = [_tw(y) for y in ys]
    col_w = [max(1, xtw[i + 1] - xtw[i]) for i in range(nc)]
    row_h = [max(1, ytw[i + 1] - ytw[i]) for i in range(nr)]

    sizes = [r["size"] for c in t["cells"] for r in c["runs"]]
    fonts = [r["font"] for c in t["cells"] for r in c["runs"]]
    ctx = {"font": max(set(fonts), key=fonts.count) if fonts else _FONT_FAMILIES["serif"][0],
           "size_hp": max(2, int(round((statistics.median(sizes) if sizes else 11.0) * 2))),
           "loose_h": loose_h}

    def edge(o, pos, a, b):
        if not styled:
            return None
        cov, best = _cover(segs, o, pos, a, b, tol)
        return best if cov >= LAYOUT_TABLE_EDGE_COVER else None

    def bw(info):
        return max(2, min(96, int(round(info["w"] * 8)))) / 8.0 if info else 0.0

    # Границы всех кусков ячеек (с учётом объединений) — заранее, чтобы по
    # ним посчитать высоты строк.
    owner = t["owner"]
    pieces = {}
    row_top = [0.0] * nr
    row_bot = [0.0] * nr
    for r in range(nr):
        for c in range(nc):
            cell = owner[r][c]
            if cell["c0"] != c:
                continue
            c0, c1, r0, r1 = cell["c0"], cell["c1"], cell["r0"], cell["r1"]
            first, last = r == r0, r == r1 - 1
            e = {"top": edge("h", ys[r0], xs[c0], xs[c1]) if first else None,
                 "bottom": edge("h", ys[r1], xs[c0], xs[c1]) if last else None,
                 "left": edge("v", xs[c0], ys[r0], ys[r1]),
                 "right": edge("v", xs[c1], ys[r0], ys[r1])}
            pieces[(r, c)] = e
            row_top[r] = max(row_top[r], bw(e["top"]))
            row_bot[r] = max(row_bot[r], bw(e["bottom"]))
    # Общая граница между строками r и r+1 — одна линия: берём наибольшую
    # из «нижней» строки r и «верхней» строки r+1.
    line_w = [0.0] * (nr + 1)
    line_w[0] = row_top[0]
    line_w[nr] = row_bot[nr - 1]
    for k in range(1, nr):
        line_w[k] = max(row_bot[k - 1], row_top[k])
    tr_h = [max(20, row_h[r] - _tw((line_w[r] + line_w[r + 1]) / 2.0)) for r in range(nr)]

    bodies = {}
    for cell in t["cells"]:
        bodies[id(cell)] = _cell_body_xml(cell, ctx)

    rows_xml = []
    for r in range(nr):
        tcs = []
        for c in range(nc):
            cell = owner[r][c]
            if cell["c0"] != c:
                continue
            c0, c1, r0, r1 = cell["c0"], cell["c1"], cell["r0"], cell["r1"]
            width = sum(col_w[c0:c1])
            first = r == r0
            e = pieces[(r, c)]
            pr = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
            if c1 - c0 > 1:
                pr.append(f'<w:gridSpan w:val="{c1 - c0}"/>')
            if r1 - r0 > 1:
                pr.append('<w:vMerge w:val="restart"/>' if first else '<w:vMerge/>')
            pr.append("<w:tcBorders>" + _border("top", e["top"]) + _border("left", e["left"])
                      + _border("bottom", e["bottom"]) + _border("right", e["right"])
                      + "</w:tcBorders>")
            if styled and cell.get("fill"):
                pr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{cell["fill"]}"/>')
            body, valign, tdir = bodies[id(cell)]
            if tdir:
                pr.append(f'<w:textDirection w:val="{tdir}"/>')
            pr.append(f'<w:vAlign w:val="{valign}"/>')
            if not first:
                body = ('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" '
                        'w:lineRule="exact"/><w:rPr><w:sz w:val="2"/></w:rPr></w:pPr></w:p>')
            tcs.append(f'<w:tc><w:tcPr>{"".join(pr)}</w:tcPr>{body}</w:tc>')
        rows_xml.append(f'<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="{tr_h[r]}" '
                        f'w:hRule="atLeast"/></w:trPr>{"".join(tcs)}</w:tr>')

    left_w = max([bw(pieces[(r, 0)]["left"]) for r in range(nr) if (r, 0) in pieces] or [0.0])
    last_c = [(r, owner[r][nc - 1]["c0"]) for r in range(nr)]
    right_w = max([bw(pieces[k]["right"]) for k in last_c if k in pieces] or [0.0])
    geom = {"x": xs[0], "y": ys[0], "w": xs[-1] - xs[0], "h": ys[-1] - ys[0],
            "left_w": left_w, "right_w": right_w, "top_w": line_w[0], "bottom_w": line_w[nr]}

    mar = _tw(LAYOUT_TABLE_CELL_MAR_PT)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_w)
    xml = (
        f'<w:tbl><w:tblPr>'
        f'<w:tblW w:w="{sum(col_w)}" w:type="dxa"/><w:tblInd w:w="0" w:type="dxa"/>'
        f'<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
        f'<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        f'<w:tblLayout w:type="fixed"/>'
        f'<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="{mar}" w:type="dxa"/>'
        f'<w:bottom w:w="0" w:type="dxa"/><w:right w:w="{mar}" w:type="dxa"/></w:tblCellMar>'
        f'<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" '
        f'w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>'
        f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(rows_xml)}</w:tbl>'
    )
    return xml, geom


class _DocxLayoutWriter:
    def __init__(self):
        self.doc = Document()
        self._id = 1
        self._z = 1000
        normal = self.doc.styles["Normal"]
        normal.font.size = Pt(1)
        pf = normal.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        self._first = True

    def _next_id(self):
        self._id += 1
        return self._id

    def new_page(self, w_pt, h_pt):
        if self._first:
            section = self.doc.sections[0]
            self._first = False
        else:
            section = self.doc.add_section(WD_SECTION.NEW_PAGE)
        section.orientation = WD_ORIENT.LANDSCAPE if w_pt > h_pt else WD_ORIENT.PORTRAIT
        section.page_width = Pt(w_pt)
        section.page_height = Pt(h_pt)
        for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin",
                     "header_distance", "footer_distance", "gutter"):
            setattr(section, attr, Pt(0))
        # Единственный абзац потока на странице: в нём якоря фона и надписей.
        self.para = self.doc.add_paragraph()
        self.para.paragraph_format.space_after = Pt(0)
        return self.para

    def _append(self, xml):
        self.para._p.append(fitz_safe_fromstring(xml))

    def add_table_box(self, tbl_xml, geom):
        """Таблица в прозрачной надписи, привязанной к странице.

        Плавающая таблица Word (w:tblpPr) рисует левую границу левее точки
        привязки, и в Word эта граница пропадала (стр. 6–7). В надписи
        таблица стоит в обычном потоке: левая граница начинается у левого
        поля надписи, а поля (LAYOUT_TABLE_BOX_PAD_PT) не дают её обрезать.
        Надпись подстраивает высоту под содержимое (spAutoFit) — если в
        ячейку допишут текст, строка вырастет, а не скроется."""
        pad = LAYOUT_TABLE_BOX_PAD_PT
        # Word начинает таблицу с внешнего края левой границы, а сетка PDF —
        # это середины линий: сдвигаем на половину толщины.
        x = geom["x"] - geom["left_w"] / 2.0 - pad
        y = geom["y"] - geom["top_w"] / 2.0 - pad
        w = geom["w"] + (geom["left_w"] + geom["right_w"]) / 2.0 + 2 * pad + 2.0
        h = geom["h"] + (geom["top_w"] + geom["bottom_w"]) / 2.0 + 2 * pad + 2.0
        X, Y = int(x * _EMU_PER_PT), int(y * _EMU_PER_PT)
        cx, cy = max(1, int(w * _EMU_PER_PT)), max(1, int(h * _EMU_PER_PT))
        ins = int(pad * _EMU_PER_PT)
        pid = self._next_id()
        self._z += 1
        tail = ('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>'
                '<w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr></w:pPr></w:p>')
        xml = (
            f'<w:r {_NS_DECL}><w:rPr><w:noProof/></w:rPr>'
            f'<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{self._z}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{X}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{Y}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapNone/><wp:docPr id="{pid}" name="Table {pid}"/><wp:cNvGraphicFramePr/>'
            f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp><wps:cNvSpPr txBox="1"/>'
            f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>'
            f'<wps:txbx><w:txbxContent>{tbl_xml}{tail}</w:txbxContent></wps:txbx>'
            f'<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="{ins}" tIns="{ins}" rIns="{ins}" bIns="{ins}" '
            f'anchor="t" anchorCtr="0" upright="1"><a:spAutoFit/></wps:bodyPr>'
            f'</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>'
            f'</mc:Choice></mc:AlternateContent></w:r>'
        )
        self._append(xml)

    def add_background(self, img_bytes, w_pt, h_pt, x_pt=0.0, y_pt=0.0,
                       name=None, z=1, ellipse=False, behind=True):
        """Неподвижная графика страницы (фото, рисунки, повёрнутые подписи),
        обрезанная по содержимому: x_pt/y_pt — левый верхний угол.

        name — рисунок это отдельный объект страницы (см. _split_page_graphics):
        он получает имя и слой z, не заблокирован, а ellipse обрезает его
        овалом. behind=False — перед текстом (но под надписями: их z больше).
        Без name — прежний заблокированный «Graphics N»."""
        rid, _ = self.doc.part.get_or_add_image(io.BytesIO(img_bytes))
        cx, cy = int(w_pt * _EMU_PER_PT), int(h_pt * _EMU_PER_PT)
        X, Y = int(x_pt * _EMU_PER_PT), int(y_pt * _EMU_PER_PT)
        pid = self._next_id()
        xml = (
            f'<w:r {_NS_DECL}><w:rPr><w:noProof/></w:rPr><w:drawing>'
            f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{z}" behindDoc="{1 if behind else 0}" locked="{0 if name else 1}" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{X}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{Y}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapNone/><wp:docPr id="{pid}" name="{_xml_escape(name or f"Graphics {pid}")}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="{_xml_escape(name or f"background{pid}")}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="{"ellipse" if ellipse else "rect"}"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
        )
        self._append(xml)

    def add_shape(self, g):
        """Плашка или линия PDF — настоящая фигура Word за текстом.

        g: kind "rect" | "line", x/y/w/h (pt, левый верхний угол; у линии одна
        из сторон 0), color RRGGBB, alpha, line_w и cap (только линия), name, z,
        behind (за текстом или перед ним, но под надписями).
        Линия центрируется на своей оси — как штрих в PDF."""
        cx, cy = int(g["w"] * _EMU_PER_PT), int(g["h"] * _EMU_PER_PT)
        X, Y = int(g["x"] * _EMU_PER_PT), int(g["y"] * _EMU_PER_PT)
        alpha = int(round(g["alpha"] * 100000))
        clr = (f'<a:srgbClr val="{g["color"]}">'
               + (f'<a:alpha val="{alpha}"/>' if alpha < 100000 else "") + '</a:srgbClr>')
        if g["kind"] == "line":
            nv, geom = "<wps:cNvCnPr/>", "line"
            paint = (f'<a:ln w="{max(1, int(round(g["line_w"] * _EMU_PER_PT)))}" cap="{g["cap"]}">'
                     f'<a:solidFill>{clr}</a:solidFill></a:ln>')
        else:
            cx, cy = max(1, cx), max(1, cy)
            nv, geom = "<wps:cNvSpPr/>", "rect"
            paint = f'<a:solidFill>{clr}</a:solidFill><a:ln><a:noFill/></a:ln>'
        pid = self._next_id()
        xml = (
            f'<w:r {_NS_DECL}><w:rPr><w:noProof/></w:rPr>'
            f'<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{g["z"]}" behindDoc="{1 if g["behind"] else 0}" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{X}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{Y}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapNone/><wp:docPr id="{pid}" name="{_xml_escape(g["name"])}"/><wp:cNvGraphicFramePr/>'
            f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp>{nv}'
            f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>{paint}</wps:spPr>'
            f'<wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>'
            f'</mc:Choice></mc:AlternateContent></w:r>'
        )
        self._append(xml)

    def add_text_segment(self, seg):
        runs = seg["runs"]
        head = runs[0]
        size_max = max(r["size"] for r in runs)
        asc = _FONT_FAMILIES[head["fam"]][2]
        x = head["x0"]
        y = min(r["origin_y"] for r in runs) - asc * size_max
        width = max(r["x1"] for r in runs) - x
        height = size_max * 1.25
        # Перенос в надписи выключен, но LibreOffice обрезает текст по рамке,
        # поэтому рамку берём с запасом — на положение текста это не влияет.
        cx = max(1, int((width * 1.3 + 2 * size_max) * _EMU_PER_PT))
        cy = max(1, int(height * _EMU_PER_PT))
        X, Y = int(x * _EMU_PER_PT), int(y * _EMU_PER_PT)

        # Пробел-вставка между кусками строки подчёркивается/выделяется,
        # если подчёркнуты/выделены оба соседа (иначе линия рвётся).
        deco = []
        for i, r in enumerate(runs):
            ul, sh = r.get("underline"), r.get("shade")
            if r["text"].isspace() and 0 < i < len(runs) - 1:
                a, b = runs[i - 1], runs[i + 1]
                ul = a.get("underline") if a.get("underline") and b.get("underline") else None
                sh = a.get("shade") if a.get("shade") and a.get("shade") == b.get("shade") else None
            deco.append((ul, sh))

        run_xml = []
        for r, (ul, sh) in zip(runs, deco):
            sz = max(2, int(round(r["size"] * 2)))
            # Word хранит кегль с шагом 0.5 pt — подгоняем ширину под
            # фактический (округлённый) кегль, иначе строки укорачиваются.
            scale, sp = _fit_width(r["text"], sz / 2.0, r["fam"], r["bold"],
                                   r["italic"], r["x1"] - r["x0"])
            f = _xml_escape(r["font"])
            rpr = (f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>'
                   + ("<w:b/><w:bCs/>" if r["bold"] else "")
                   + ("<w:i/><w:iCs/>" if r["italic"] else "")
                   + "<w:noProof/>"
                   + f'<w:color w:val="{r["color"]}"/>'
                   + (f'<w:spacing w:val="{sp}"/>' if sp else "")
                   + (f'<w:w w:val="{scale}"/>' if scale != 100 else "")
                   + f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'
                   + _u_xml(ul) + _shd_xml(sh))
            run_xml.append(f'<w:r><w:rPr>{rpr}</w:rPr>'
                           f'<w:t xml:space="preserve">{_xml_escape(r["text"])}</w:t></w:r>')

        pid = self._next_id()
        self._z += 1
        xml = (
            f'<w:r {_NS_DECL}><w:rPr><w:noProof/></w:rPr>'
            f'<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{self._z}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{X}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{Y}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapNone/><wp:docPr id="{pid}" name="Text {pid}"/><wp:cNvGraphicFramePr/>'
            f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp><wps:cNvSpPr txBox="1"/>'
            f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>'
            f'<wps:txbx><w:txbxContent><w:p><w:pPr>'
            f'<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
            f'<w:ind w:left="0" w:right="0" w:firstLine="0"/><w:jc w:val="left"/>'
            f'<w:rPr><w:sz w:val="2"/></w:rPr></w:pPr>{"".join(run_xml)}</w:p></w:txbxContent></wps:txbx>'
            f'<wps:bodyPr rot="0" vert="horz" wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" '
            f'anchor="t" anchorCtr="0" upright="1"><a:noAutofit/></wps:bodyPr>'
            f'</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing>'
            f'</mc:Choice></mc:AlternateContent></w:r>'
        )
        self._append(xml)

    def _modern_compat(self):
        """Шаблон python-docx помечен как Word 2010 (compatibilityMode 14),
        из-за чего Word открывает файл в «режиме совместимости»."""
        try:
            settings = self.doc.settings.element
            for el in settings.iter(qn("w:compatSetting")):
                if el.get(qn("w:name")) == "compatibilityMode":
                    el.set(qn("w:val"), "15")
            zoom = settings.find(qn("w:zoom"))
            if zoom is not None and zoom.get(qn("w:percent")) is None:
                zoom.set(qn("w:percent"), "100")
        except (AttributeError, KeyError, ValueError, TypeError):
            logger.warning("Could not adjust DOCX compatibility settings", exc_info=True)

    def save(self, path):
        self._modern_compat()
        self.doc.save(path)


def fitz_safe_fromstring(xml: str):
    from lxml import etree
    return etree.fromstring(xml.encode("utf-8"))


# Графика страницы отдельными объектами Word. Раньше всё, что не текст (плашки,
# линии, логотип, фото), печаталось одним фоновым рисунком «Graphics N»: в Word
# его нельзя было выделить и сдвинуть по частям. Теперь плашки и линии PDF —
# настоящие фигуры Word, встроенные картинки — отдельные рисунки по своей рамке
# (с овальной обрезкой, если в PDF фото обрезано кругом), а остальная графика
# (логотипы, кольца, значки) рендерится с прозрачным фоном и режется по пустым
# промежуткам на отдельные рисунки.
LAYOUT_GFX_CLUSTER_GAP_PT = 12.0   # графика ближе этого — один рисунок (знак + надпись логотипа)
LAYOUT_GFX_MAX_OBJECTS = 200       # больше объектов на странице — один растр, как раньше


def _bands(flags, gap):
    """Отрезки [a, b) подряд идущих True; разрыв не шире gap их не разделяет."""
    idx = np.flatnonzero(flags)
    if not len(idx):
        return []
    cut = np.flatnonzero(np.diff(idx) > gap)
    return list(zip(idx[np.r_[0, cut + 1]].tolist(), (idx[np.r_[cut, len(idx) - 1]] + 1).tolist()))


def _xy_cut(mask, gap, x0=0, y0=0):
    """Маску графики режет по пустым полосам шире gap (рекурсивно, XY-cut).
    Возвращает рамки (x0, y0, x1, y1) в px — по одной на отдельный рисунок."""
    ys = _bands(mask.any(axis=1), gap)
    xs = _bands(mask.any(axis=0), gap)
    if len(ys) > 1:
        return [b for a, c in ys for b in _xy_cut(mask[a:c], gap, x0, y0 + a)]
    if len(xs) > 1:
        return [b for a, c in xs for b in _xy_cut(mask[:, a:c], gap, x0 + a, y0)]
    if not ys:
        return []
    return [(x0 + xs[0][0], y0 + ys[0][0], x0 + xs[0][1], y0 + ys[0][1])]


def _rect_inside(r, outers, tol=0.5):
    """r целиком лежит в одной из рамок outers (так же MuPDF решает, что графика
    «покрыта» областью redaction)."""
    return any(o.x0 - tol <= r.x0 and o.y0 - tol <= r.y0 and r.x1 <= o.x1 + tol
               and r.y1 <= o.y1 + tol for o in outers)


def _gfx_skip(pno, why):
    """Страница остаётся одним растром, как раньше: причина уходит вызывающему
    (лог и warning в ответе API), чтобы не искать её в консоли сервера."""
    raise RuntimeError(why)


def _split_page_graphics(src, page, pno, prims, img_infos, clear, text_rects, keep_rot, dpi):
    """Графика текстовой страницы -> отдельные объекты Word.

    Простые рисунки PDF из prims (плашки и прямые линии, которые не ушли в
    таблицы и подчёркивания) становятся фигурами; встроенные картинки — своими
    рисунками (обрезанные овалом — с овальной обрезкой); остаток (кривые,
    логотипы, значки, повёрнутые подписи) рендерится с прозрачным фоном без
    всего перечисленного и режется на рисунки по пустым промежуткам.
    Возвращает объекты в порядке слоёв ({"kind": "rect" | "line" | "pic", ...},
    координаты в pt) или None — тогда вызывающий оставляет один растр, как раньше."""
    from collections import Counter
    if not hasattr(fitz, "PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED"):
        return _gfx_skip(pno, f"нужен PyMuPDF 1.24.2+, установлен {getattr(fitz, 'VersionBind', '?')}")
    segs, fills, others, meta = prims
    ext = page.get_drawings(extended=True)
    paint = [d for d in ext if d["type"] not in ("clip", "group")]
    if len(paint) != len(meta):   # seq в prims — номер рисунка без clip/group
        return _gfx_skip(pno, "список рисунков не сошёлся с prims")
    clips = [d for d in ext if d["type"] == "clip"]
    clear = [fitz.Rect(c) for c in clear]
    w_pt, h_pt = page.rect.width, page.rect.height

    # Порядок отрисовки: фигуры, картинки и остаток растра должны лечь слоями так
    # же, как в PDF (полупрозрачная плашка поверх фото, линия поверх картинки).
    # Журнал отрисовки даёт индекс каждого рисунка и каждой картинки.
    order, img_pos, skip = [], [], False
    for k, (kind, _) in enumerate(page.get_bboxlog()):
        if kind == "fill-image":
            img_pos.append(k)
        elif kind in ("fill-path", "stroke-path"):
            if skip:   # вторая запись рисунка «заливка + обводка»
                skip = False
                continue
            if len(order) >= len(paint) or (paint[len(order)]["type"] == "s") != (kind == "stroke-path"):
                return _gfx_skip(pno, "журнал отрисовки не сошёлся с рисунками")
            skip = paint[len(order)]["type"] == "fs"
            order.append(k)
    if len(order) != len(paint) or len(img_pos) != len(img_infos):
        return _gfx_skip(pno, "журнал отрисовки не сошёлся с рисунками/картинками")

    # Фигуры: рисунок целиком простой, не пунктир, не перенесён в таблицу или
    # подчёркивание (иначе он уже убран из растра), и не точка нулевой длины.
    parts = {}
    for e in list(fills) + list(segs):   # заливка под обводкой
        parts.setdefault(e["seq"], []).append(e)
    shapes = [seq for seq in sorted(parts)
              if meta[seq]["simple"] and not _rect_inside(meta[seq]["rect"], clear)
              and (paint[seq].get("dashes") or "[] 0") == "[] 0"
              and all(e["b"] - e["a"] >= 0.1 for e in parts[seq] if "o" in e)]

    # Встроенные картинки: прямые, без маски; обрезка — только овалом.
    pics = []
    for n, info in enumerate(img_infos):
        r = fitz.Rect(info["bbox"])
        a, b, c, d = info["transform"][:4]
        if (not info.get("xref") or info.get("has-mask") or a <= 0 or d <= 0
                or abs(b) > 1e-3 or abs(c) > 1e-3):
            continue
        oval = any(all(it[0] == "c" for it in k["items"])
                   and all(abs(u - v) <= 1.5 for u, v in zip(k["scissor"], r)) for k in clips)
        if not oval and any(k["scissor"].intersects(r) and not _rect_inside(r, [k["scissor"]])
                            for k in clips):
            continue   # другая обрезка: картинка остаётся в растре
        try:
            pix = fitz.Pixmap(src, info["xref"])
            if pix.alpha:
                continue
            if pix.colorspace is None or pix.colorspace.n != 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception:
            logger.debug("Suppressed error in _split_page_graphics()", exc_info=True)
            continue
        pics.append({"kind": "pic", "img": _image_bytes(img), "x": r.x0, "y": r.y0,
                     "w": r.width, "h": r.height, "oval": oval, "rect": r, "pos": img_pos[n]})

    if not (shapes or pics or others):
        return None   # отделять нечего — страница как раньше

    # Точка касания для каждого рисунка-фигуры: redaction «если задето» убирает
    # из растра только его. Рамку обводки с кривыми MuPDF считает с запасом
    # 10 толщин (миттер), поэтому точка не должна попадать в оставшиеся.
    pts = {}
    while True:
        keep = [(paint[i]["rect"], (paint[i].get("width") or 1.0) * (1.0 if meta[i]["simple"] else 10.0)
                 if "s" in paint[i]["type"] else 0.0)
                for i in range(len(paint)) if i not in shapes]
        pts, bad = {}, []
        for seq in shapes:
            r = fitz.Rect(paint[seq]["rect"])
            for fx, fy in ((.5, .5), (.25, .5), (.75, .5), (.5, .25), (.5, .75),
                           (.05, .05), (.95, .95), (.05, .95), (.95, .05)):
                x, y = r.x0 + fx * r.width, r.y0 + fy * r.height
                if not any(o.x0 - g <= x <= o.x1 + g and o.y0 - g <= y <= o.y1 + g for o, g in keep):
                    pts[seq] = (x, y)
                    break
            else:
                bad.append(seq)
        if not bad:
            break
        shapes = [s for s in shapes if s not in bad]

    items, names, seen = [], {}, set()

    def name_of(base, numbered=False):
        n = names[base] = names.get(base, 0) + 1
        return f"{base} {n}" if numbered or n > 1 else base

    def add(it, base, numbered, pos):
        # Двойная отрисовка одного и того же (так LibreOffice рисует заливки и
        # границы) — один объект; полупрозрачные слои не склеиваем.
        key = tuple(sorted((k, round(v, 2) if isinstance(v, float) else v) for k, v in it.items()))
        if it["alpha"] >= 1.0 and key in seen:
            return
        seen.add(key)
        it["name"], it["pos"] = name_of(base, numbered), pos
        items.append(it)

    for seq in shapes:
        d = paint[seq]
        for e in parts[seq]:
            if "rect" in e:
                r = e["rect"]
                ch = [int(e["color"][i:i + 2], 16) for i in (0, 2, 4)]
                op = d.get("fill_opacity")
                add({"kind": "rect", "x": r.x0, "y": r.y0, "w": r.width, "h": r.height,
                     "color": e["color"], "alpha": 1.0 if op is None else op},
                    "Gray block" if max(ch) - min(ch) <= 16 else "Block", False, order[seq])
            else:
                horiz = e["o"] == "h"
                op = d.get("stroke_opacity" if "s" in d["type"] else "fill_opacity")
                cap = int((d.get("lineCap") or (0,))[0]) if "s" in d["type"] else 0
                add({"kind": "line", "x": e["a"] if horiz else e["p"],
                     "y": e["p"] if horiz else e["a"],
                     "w": e["b"] - e["a"] if horiz else 0.0,
                     "h": 0.0 if horiz else e["b"] - e["a"],
                     "line_w": e["w"], "color": e["color"], "cap": {1: "rnd", 2: "sq"}.get(cap, "flat"),
                     "alpha": 1.0 if op is None else op}, "Line", True, order[seq])
    for p in pics:
        p["name"] = name_of("Avatar" if p["oval"] else "Picture")
        items.append(p)

    # Растр остатка: без текста, без вынесенных фигур и картинок, фон прозрачный.
    strip = fitz.open()
    try:
        strip.insert_pdf(src, from_page=pno, to_page=pno)
        sp = strip[0]
        if pts:
            for x, y in pts.values():
                sp.add_redact_annot(fitz.Rect(x - .1, y - .1, x + .1, y + .1), fill=False)
            sp.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, text=fitz.PDF_REDACT_TEXT_NONE,
                                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
            key = lambda r: tuple(round(v, 1) for v in r)
            if (Counter(key(d["rect"]) for d in sp.get_drawings())
                    != Counter(key(paint[i]["rect"]) for i in range(len(paint)) if i not in pts)):
                return _gfx_skip(pno, "redaction задела лишнее")   # не рискуем
        if pics:
            for p in pics:
                sp.add_redact_annot(p["rect"] + (.5, .5, -.5, -.5), fill=False)
            sp.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE, text=fitz.PDF_REDACT_TEXT_NONE,
                                graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            if len(sp.get_image_info()) != len(img_infos) - len(pics):
                return _gfx_skip(pno, "redaction задела лишние картинки")
        rgba = _render_without_text(strip, 0, text_rects, dpi, keep=keep_rot, clear=clear, alpha=True)
    finally:
        strip.close()
    alpha = np.asarray(rgba)[:, :, 3]
    sx, sy = w_pt / float(rgba.width), h_pt / float(rgba.height)
    # слой остатка — по самому нижнему из рисунков PDF, попавших в его рамку
    rest = [(order[i], fitz.Rect(paint[i]["rect"])) for i in range(len(paint)) if i not in pts]
    rest += [(img_pos[n], fitz.Rect(info["bbox"])) for n, info in enumerate(img_infos)
             if not any(p["pos"] == img_pos[n] for p in pics)]
    for x0, y0, x1, y1 in _xy_cut(alpha > 8, max(1, int(LAYOUT_GFX_CLUSTER_GAP_PT / sx))):
        box = (max(0, x0 - 1), max(0, y0 - 1), min(rgba.width, x1 + 1), min(rgba.height, y1 + 1))
        part = rgba.crop(box)
        if np.asarray(part)[:, :, 3].min() == 255:
            data = _image_bytes(part.convert("RGB"))
        else:
            buf = io.BytesIO()
            part.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
        zone = fitz.Rect(box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)
        under = [k for k, r in rest if zone.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))]
        items.append({"kind": "pic", "img": data, "x": zone.x0, "y": zone.y0,
                      "w": zone.width, "h": zone.height, "oval": False,
                      "name": name_of("Graphic", True), "pos": min(under, default=len(order) + len(img_pos))})
    if len(items) > LAYOUT_GFX_MAX_OBJECTS:
        return _gfx_skip(pno, f"объектов больше {LAYOUT_GFX_MAX_OBJECTS}")
    # Word не гарантирует порядок нескольких объектов «за текстом»: серая плашка
    # ложилась поверх фото и логотипа. Поэтому за текстом остаются только объекты,
    # которые не перекрывают более нижние (между ними порядок не важен), а всё, что
    # лежит поверх другого объекта, ставится перед текстом: «перед текстом» Word
    # всегда рисует выше «за текстом». Слои z (< 1000) остаются под надписями.
    items.sort(key=lambda it: it["pos"])
    boxes = []
    for z, it in enumerate(items, 1):
        pad = max(it.get("line_w", 0.0) / 2.0, 0.25)
        box = (it["x"] - pad, it["y"] - pad, it["x"] + it["w"] + pad, it["y"] + it["h"] + pad)
        it["behind"] = not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3]
                               for o in boxes)
        it["z"] = z
        boxes.append(box)
    return items


def pdf_layout_to_docx(pdf_path: str, out_path: str, lang: str = OCR_LANG,
                       dpi: int = LAYOUT_BG_DPI) -> dict:
    """PDF -> DOCX страница в страницу. Возвращает статистику."""
    src = fitz.open(pdf_path)
    writer = _DocxLayoutWriter()
    stats = {"pages": src.page_count, "ocr_pages": 0, "images": 0, "tables": 0}
    try:
        for pno in range(src.page_count):
            page = src[pno]
            w_pt, h_pt = page.rect.width, page.rect.height
            writer.new_page(w_pt, h_pt)

            # Для вёрстки «скан» — только страница вовсе без текстового слоя:
            # у обложек и фотостраниц текста мало, но он настоящий.
            scan = _layout_page_is_scan(page)
            broken = (not scan) and page_text_is_broken(page)
            invisible = [] if (scan or broken) else _invisible_text_rects(page)

            text_page = not (scan or broken or invisible)
            vector_ok = not scan and not invisible
            if text_page:
                segments, rects = _collect_page_text(page)

            # Векторная графика страницы — один раз для таблиц и подчёркиваний.
            prims = None
            if vector_ok and (LAYOUT_EDITABLE_TABLES or LAYOUT_NATIVE_DECORATIONS):
                try:
                    prims = _vector_table_primitives(page, with_meta=True)
                except Exception as e:
                    logger.warning(f"Графика стр. {pno + 1} не разобрана: {e}")
            try:
                img_infos = page.get_image_info(xrefs=True)
                img_rects = [fitz.Rect(i["bbox"]) for i in img_infos]
            except Exception:
                logger.debug("Suppressed error in pdf_layout_to_docx()", exc_info=True)
                img_infos, img_rects = [], []

            # Подчёркивания и выделение цветом -> формат текста (только для
            # настоящего текстового слоя: у OCR-текста нет точных координат).
            hl_fills, deco_clear = set(), []
            if prims is not None and text_page and LAYOUT_NATIVE_DECORATIONS:
                try:
                    # все рамки (и одиночные): их линии — не подчёркивания
                    grid = _find_grid_tables(prims[0], w_pt, h_pt, allow_single=True,
                                             fills=prims[1])
                    skip = set()
                    for g in grid:
                        skip |= g["seg_ids"]
                    hl_fills, deco_clear = _text_decorations(segments, prims[0], prims[1],
                                                             prims[3], grid, skip)
                except Exception as e:
                    logger.warning(f"Подчёркивания стр. {pno + 1} не перенесены: {e}")
                    hl_fills, deco_clear = set(), []
                    for sg in segments:
                        for r in sg["runs"]:
                            r.pop("underline", None)
                            r.pop("shade", None)

            # Таблицы с векторной сеткой (обычный и битый текстовый слой).
            tables, loose_h, rotated_in_tables = [], [], []
            if LAYOUT_EDITABLE_TABLES and vector_ok:
                try:
                    pts = None
                    if text_page:
                        pts = [((r["x0"] + r["x1"]) / 2, r["origin_y"] - 0.3 * r["size"])
                               for sg in segments for r in sg["runs"] if r["text"].strip()]
                    tables, loose_h = _detect_vector_tables(page, img_rects, prims, hl_fills, pts)
                except Exception as e:
                    logger.warning(f"Таблицы на стр. {pno + 1} не распознаны: {e}")
                    tables, loose_h = [], []
            clear = [t["clear"] for t in tables if t.get("clean") and t.get("clear")] + deco_clear
            keep_rot = _rotated_text_rects(page)
            if tables:
                rotated_in_tables = [rl for rl in _rotated_lines(page)
                                     if _table_for_point(tables, (rl["rect"].x0 + rl["rect"].x1) / 2,
                                                         (rl["rect"].y0 + rl["rect"].y1) / 2)]
                in_tab = [rl["rect"] for rl in rotated_in_tables]
                keep_rot = [k for k in keep_rot if not any(k == r for r in in_tab)]

            # Плашки, линии, фото и значки — отдельными объектами Word, а не одним
            # фоновым рисунком (только для настоящего текстового слоя).
            gfx = None
            if not (text_page and prims is not None and not page.rotation):
                logger.info(f"Графика стр. {pno + 1} одним рисунком: "
                      + ("страница распознана как скан/битый текст/OCR-слой" if not text_page
                         else "векторная графика не разобрана" if prims is None else "страница повёрнута"))
            else:
                try:
                    gfx = _split_page_graphics(src, page, pno, prims, img_infos, clear,
                                               rects, keep_rot, dpi)
                except Exception as e:
                    logger.warning(f"Графика стр. {pno + 1} не разделена: {e}")
                    stats.setdefault("graphics_notes", []).append(f"стор. {pno + 1}: {e}")
                    gfx = None

            if scan or broken or invisible:
                # Текст страницы — пиксели (скан или OCR-слой поверх скана)
                # либо текстовый слой битый: распознаём заново.
                if broken:
                    _, rects = _collect_page_text(page)
                    rects = rects or [fitz.Rect(b[:4]) for b in page.get_text("blocks")]
                    bg = _render_without_text(src, pno, rects, OCR_DPI,
                                              keep=keep_rot, clear=clear)
                else:
                    bg = _render_without_text(src, pno, [], OCR_DPI)
                full = page.get_pixmap(dpi=OCR_DPI, alpha=False)
                full_img = Image.frombytes("RGB", (full.width, full.height), full.samples)
                try:
                    segments, boxes = _ocr_segments(full_img, 72.0 / OCR_DPI, lang)
                except Exception as e:
                    logger.warning(f"OCR страницы {pno + 1} не удался: {e}")
                    segments, boxes = [], []
                if segments and not _ocr_is_meaningful(segments):
                    segments = []
                if segments:
                    stats["ocr_pages"] += 1
                    if not broken:
                        bg = _inpaint_boxes(bg, boxes)
                        # Таблицы скана: линии сетки — пиксели, ищем их на растре.
                        if LAYOUT_EDITABLE_TABLES:
                            try:
                                tables, line_boxes = _detect_raster_tables(
                                    full_img, 72.0 / OCR_DPI, w_pt, h_pt, ocr_boxes=boxes)
                            except Exception as e:
                                logger.warning(f"Таблицы скана на стр. {pno + 1} не распознаны: {e}")
                                tables, line_boxes = [], []
                            if tables:
                                bg = _inpaint_boxes(bg, line_boxes, pad=1)
                elif not broken:
                    bg = full_img  # распознать не удалось — оставляем страницу как есть
                    tables = []
                if dpi != OCR_DPI:
                    k = dpi / float(OCR_DPI)
                    bg = bg.resize((max(1, int(bg.width * k)), max(1, int(bg.height * k))),
                                   getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1))
            elif gfx is None:
                bg = _render_without_text(src, pno, rects, dpi,
                                          keep=keep_rot, clear=clear)

            if tables:
                segments = _distribute_table_text(tables, segments, rotated_in_tables)

            # Всё, что стало текстом, таблицами, подчёркиванием и выделением,
            # из растра убрано. Пустой растр не вставляется вовсе, остальное
            # (фото, рисунки) — только в границах содержимого, а не листом на
            # всю страницу, который в Word легко случайно схватить и сдвинуть.
            if gfx is not None:
                for g in gfx:
                    if g["kind"] == "pic":
                        writer.add_background(g["img"], g["w"], g["h"], g["x"], g["y"],
                                              g["name"], g["z"], g["oval"], g["behind"])
                        stats["images"] += 1
                    else:
                        writer.add_shape(g)
            elif not _is_blank(bg):
                box = _content_bbox(bg)
                if box:
                    sx, sy = w_pt / float(bg.width), h_pt / float(bg.height)
                    part = bg.crop(box)
                    writer.add_background(_image_bytes(part),
                                          (box[2] - box[0]) * sx, (box[3] - box[1]) * sy,
                                          box[0] * sx, box[1] * sy)
                    stats["images"] += 1
            for t in tables:
                try:
                    tbl_xml, geom = _table_xml(t, loose_h)
                    writer.add_table_box(tbl_xml, geom)
                    stats["tables"] += 1
                except Exception as e:
                    # Таблицу собрать не удалось — её текст хотя бы надписями.
                    logger.warning(f"Таблица на стр. {pno + 1} не собрана: {e}")
                    for cell in t["cells"]:
                        for run in cell["runs"]:
                            segments.append({"runs": [run]})
            for seg in segments:
                writer.add_text_segment(seg)
    finally:
        src.close()
    writer.save(out_path)
    return stats
