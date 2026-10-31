"""Book typesetting of a DOCX before it is printed to PDF (page, fonts, hyphenation)."""
import logging
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

logger = logging.getLogger(__name__)

# ============== КНИЖНАЯ ВЕРСТКА DOCX ПЕРЕД PDF ==============
# Параметры подобраны под эталонную верстку книги (~424 стр. A4).
BOOK_PAGE = (21.0, 29.7)              # A4: ширина, высота, см
BOOK_MARGINS = (2.0, 2.0, 2.5, 2.5)   # top, bottom, left, right, см
BOOK_FONT = "Times New Roman"
BOOK_SIZE_PT = 14
BOOK_LINE_SPACING = 1.3
BOOK_INDENT_CM = 1.25
BOOK_LANG = "ru-RU"

_HEADING_RE = re.compile(r"^(Глава|Часть|Раздел|ГЛАВА|ЧАСТЬ|РАЗДЕЛ)\b")
_SERVICE_RE = re.compile(r"[\dIVXLC]{1,4}")


def _set_style_font(style, name, size_pt, lang=None):
    """Шрифт нужно прописать во все слоты rFonts, иначе кириллица
    рендерится дефолтным шрифтом LibreOffice."""
    style.font.name = name
    style.font.size = Pt(size_pt)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)
    if lang:
        el = rpr.find(qn("w:lang"))
        if el is None:
            el = OxmlElement("w:lang")
            rpr.append(el)
        el.set(qn("w:val"), lang)


def _enable_hyphenation(doc, zone_twips=284):
    """Автоперенос. Требует пакет hyphen-ru в образе, иначе LibreOffice
    молча проигнорирует флаг."""
    settings = doc.settings.element
    for tag, val in (("w:autoHyphenation", "true"),
                     ("w:doNotHyphenateCaps", "true"),
                     ("w:hyphenationZone", str(zone_twips))):
        el = settings.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            settings.append(el)
        el.set(qn("w:val"), val)


def _is_book_heading(para) -> bool:
    """Заголовок определяем по стилю и явным признакам.
    Старое условие (len(text) < 40 and not text.endswith('.')) ошибочно
    срабатывало на 662 обычных абзацах из 2302."""
    style = para.style.name or ""
    if style.startswith("Heading") or style in ("Title", "Subtitle"):
        return True
    text = para.text.strip()
    if not text or len(text) > 70:
        return False
    if _HEADING_RE.match(text):
        return True
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return True
    return False


def _is_service_line(text: str) -> bool:
    """Колонтитулы и номера страниц, попавшие в текст из FB2/OCR-скана."""
    return bool(_SERVICE_RE.fullmatch(text.strip()))


def _iter_all_paragraphs(doc):
    """doc.paragraphs не видит абзацы внутри таблиц."""
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def format_book_docx(docx_path: str,
                     page=BOOK_PAGE,
                     margins=BOOK_MARGINS,
                     font=BOOK_FONT,
                     size_pt=BOOK_SIZE_PT,
                     line_spacing=BOOK_LINE_SPACING,
                     hyphenate=True):
    """Приводит DOCX к книжной верстке: формат страницы, поля, красная
    строка, выключка по ширине, книжный шрифт и переносы.

    Исключения намеренно не глушатся: молчаливый провал форматирования
    отдает пользователю сырой вывод pandoc под видом успешной конвертации.
    """
    doc = Document(docx_path)

    # 1. Формат страницы. Pandoc пишет пустой <w:sectPr/> без pgSz, и без
    #    явного размера LibreOffice подставляет свой дефолт (Letter).
    for section in doc.sections:
        section.page_width = Cm(page[0])
        section.page_height = Cm(page[1])
        section.top_margin = Cm(margins[0])
        section.bottom_margin = Cm(margins[1])
        section.left_margin = Cm(margins[2])
        section.right_margin = Cm(margins[3])

    # 2. Шрифт. Pandoc кладет весь текст в стиль Body Text со своим pPr
    #    (spacing before/after 180 twips), одного Normal недостаточно.
    _set_style_font(doc.styles["Normal"], font, size_pt, BOOK_LANG)
    for style_name in ("Body Text", "First Paragraph", "Compact"):
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        _set_style_font(style, font, size_pt, BOOK_LANG)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.space_after = Pt(0)

    if hyphenate:
        _enable_hyphenation(doc)

    # 3. Абзацы
    for para in _iter_all_paragraphs(doc):
        text = para.text.strip()
        if not text:
            continue
        p_format = para.paragraph_format

        if _is_service_line(text):
            p_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_format.first_line_indent = Cm(0)
            p_format.space_before = Pt(6)
            p_format.space_after = Pt(6)
            continue

        if _is_book_heading(para):
            p_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_format.first_line_indent = Cm(0)
            p_format.space_before = Pt(18)
            p_format.space_after = Pt(10)
            p_format.line_spacing = 1.0
            p_format.keep_with_next = True
            continue

        p_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_format.first_line_indent = Cm(BOOK_INDENT_CM)
        p_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p_format.line_spacing = line_spacing
        p_format.space_before = Pt(0)
        p_format.space_after = Pt(0)
        p_format.widow_control = True

    doc.save(docx_path)
