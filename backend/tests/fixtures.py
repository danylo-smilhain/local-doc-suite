"""Tiny generated input files for the characterization tests.

Every builder writes one small file into ``directory`` and returns its path.
Nothing here depends on the application code, so the same fixtures keep
working while the backend is refactored.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from pathlib import Path

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

PDF_TEXT = "Quarterly report about apples and oranges"
DOCX_TEXT = "Hello from a Word document"
PPTX_TITLE = "Slide title alpha"
EPUB_TITLE = "Chapter One"
EPUB_TEXT = "The quick brown fox jumps over the lazy dog."
FB2_AUTHOR_FIRST = "Ivan"
FB2_AUTHOR_LAST = "Petrenko"
FB2_TITLE = "Forest Tales"
FB2_TEXT = "Once upon a time in a green forest."
HTML_TEXT = "Plain web page paragraph"
TELEGRAM_CHAT = "Family Chat"
TELEGRAM_AUTHOR = "Olena"
TELEGRAM_MESSAGE = "See you tomorrow at noon"
OCR_WORD = "INVOICE"
CYRILLIC_TEXT = (
    "Привіт, світе! Це перевірка кодування тексту для конвертера.\n"
    "Він має визначити кодування і зберегти всі літери правильно.\n"
)


def _font():
    from PIL import ImageFont
    try:
        return ImageFont.truetype(DEJAVU, 64)
    except OSError:
        return ImageFont.load_default()


def text_pdf(directory: Path, name: str = "text.pdf", text: str = PDF_TEXT, pages: int = 1) -> Path:
    import fitz
    path = directory / name
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"{text} page {i + 1}", fontsize=14)
        page.insert_text((72, 130), "Second line of ordinary body text here.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def text_image(directory: Path, name: str = "scan.png", word: str = OCR_WORD) -> Path:
    from PIL import Image, ImageDraw
    path = directory / name
    img = Image.new("RGB", (900, 260), "white")
    ImageDraw.Draw(img).text((60, 80), f"{word} 2024", fill="black", font=_font())
    img.save(path)
    return path


def scanned_pdf(directory: Path, name: str = "scan.pdf", word: str = OCR_WORD) -> Path:
    """A PDF page that is only a picture of text (no text layer)."""
    import fitz
    png = text_image(directory, name + ".png", word)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(40, 60, 555, 210), filename=str(png))
    doc.save(str(path))
    doc.close()
    png.unlink()
    return path


# A full scanned page of English prose. OCR picks the language order from the
# letters it sees (app.ocr._choose_ocr_lang_order) only once a page has 200+
# letters; a lone short word like "INVOICE" can come out in look-alike
# Cyrillic when Ukrainian is installed and tried first.
SCANNED_PAGE_LINES = [
    f"{OCR_WORD} 2024",
    "The supplier delivered the goods on time and",
    "the customer paid the full amount in cash.",
    "Please keep this document for your records,",
    "it confirms payment for services rendered.",
    "The supplier delivered the goods on time and",
    "the customer paid the full amount in cash.",
    "Please keep this document for your records,",
    "it confirms payment for services rendered.",
]


# What a Canva export with a broken Cyrillic font gives as text: only the low
# byte of each letter survives ("Бренд-менеджмент" -> "\x11@5=4-<5=546<5=B").
GARBLED_LINE = "\x11@5=4-<5=546<5=B PR B0 \x1a><C=V:0FVW"
CLEAN_LINE = "Clean heading here"


SCREENSHOT_LINE = "Caption inside photo"
OVERLAY_LINE = "Overlay title"


def _outlined_lines(lines, width, height, size, color=(0, 0, 0)):
    """A one-page PDF with the lines drawn as vector outlines and no text,
    as Canva draws letters whose font it exported without a Unicode map."""
    import fitz
    src = fitz.open()
    page = src.new_page(width=width, height=height)
    for i, line in enumerate(lines):
        page.insert_text((35, 50 + i * 60), line, fontsize=size, color=color)
    svg = page.get_svg_image(text_as_path=True)
    return fitz.open(stream=fitz.open("svg", svg.encode()).convert_to_pdf(), filetype="pdf")


def garbled_text_pdf(directory: Path, name: str = "garbled.pdf") -> Path:
    """A 16:9 page like the damaged Canva deck: the readable words are vector
    outlines with a garbled text line over them, plus one line of normal
    text and a dark photo with a caption in it (text that belongs to the
    photo) under a white outlined title (text the slide puts on the photo)."""
    import fitz
    from PIL import Image, ImageDraw
    png = directory / (name + ".png")
    img = Image.new("RGB", (900, 600), (30, 50, 80))
    ImageDraw.Draw(img).text((40, 410), SCREENSHOT_LINE, fill=(230, 230, 230), font=_font())
    img.save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=1440, height=810)
    page.show_pdf_page(fitz.Rect(100, 150, 1100, 750), _outlined_lines(SCANNED_PAGE_LINES, 1000, 600, 36), 0)
    page.insert_image(fitz.Rect(1110, 540, 1410, 740), filename=str(png))
    page.show_pdf_page(fitz.Rect(1110, 545, 1410, 605), _outlined_lines([OVERLAY_LINE], 300, 60, 36, (1, 1, 1)), 0)
    page.insert_text((100, 80), CLEAN_LINE, fontsize=30)
    # a mark over the clean line that OCR cannot read as letters
    page.draw_rect(fitz.Rect(120, 62, 132, 76), color=None, fill=(0, 0, 0))
    # invisible: a viewer shows the right letters, only the text layer is wrong
    page.insert_text((100, 130), GARBLED_LINE, fontsize=30, render_mode=3)
    doc.save(str(path))
    doc.close()
    png.unlink()
    return path


def scanned_page_pdf(directory: Path, name: str = "page_scan.pdf") -> Path:
    """A PDF page that is only a picture of a full page of English text."""
    import fitz
    from PIL import Image, ImageDraw
    png = directory / (name + ".png")
    img = Image.new("RGB", (1960, 2774), "white")      # the A4 sheet, text block at the top
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(SCANNED_PAGE_LINES):
        draw.text((190, 200 + i * 120), line, fill="black", font=_font())
    img.save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # a scanner gives the whole sheet: the text block with white margins
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))
    doc.close()
    png.unlink()
    return path


CANVA_TITLE = "БРЕНД МЕНЕДЖМЕНТ"
CANVA_LATIN_LINE = "CASE для журналістів з різних міст"
CANVA_BOLD_NAME = "Марія Пальчук"


def canva_scan_pdf(directory: Path, name: str = "canva_scan.pdf") -> Path:
    """A 16:9 slide that is only a picture, coloured like the Canva decks:
    a teal border, a white card, a big orange title, and Ukrainian body text
    with an English word. The orange is as bright as the teal in grey, so
    Tesseract's own binarisation loses the title."""
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    png = directory / (name + ".png")
    img = Image.new("RGB", (2880, 1620), (77, 168, 176))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((120, 120, 2760, 1500), 40, fill="white")
    draw.text((240, 400), CANVA_TITLE, font=ImageFont.truetype(DEJAVU_BOLD, 180), fill=(255, 133, 51))
    body = ImageFont.truetype(DEJAVU, 56)
    draw.text((240, 1100), CANVA_LATIN_LINE, font=body, fill="black")
    draw.text((240, 1250), "Спікер ", font=body, fill="black")
    draw.text((240 + draw.textlength("Спікер ", font=body), 1250), CANVA_BOLD_NAME,
              font=ImageFont.truetype(DEJAVU_BOLD, 56), fill="black")
    img.save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=1440, height=810)
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))
    doc.close()
    png.unlink()
    return path


def _weightless(font_path: str) -> bytes:
    """The font file with every mark of its weight cleared (head.macStyle,
    OS/2 usWeightClass and fsSelection): a viewer draws it as it is, but
    nothing says it is bold, as with Canva's unnamed Type3 fonts."""
    import struct
    data = bytearray(Path(font_path).read_bytes())
    count = struct.unpack(">H", data[4:6])[0]
    tables = {bytes(data[12 + 16 * i:16 + 16 * i]): struct.unpack(">I", data[20 + 16 * i:24 + 16 * i])[0]
              for i in range(count)}
    struct.pack_into(">H", data, tables[b"head"] + 44, 0)
    struct.pack_into(">H", data, tables[b"OS/2"] + 4, 400)
    struct.pack_into(">H", data, tables[b"OS/2"] + 62, 0x40)
    return bytes(data)


def _unname_fonts(doc, page) -> None:
    """Every font of the page renamed "Unnamed-T3", as Canva exports them."""
    import re
    for xref, *_ in page.get_fonts():
        doc.xref_set_key(xref, "BaseFont", "/Unnamed-T3")
        descendant = int(re.search(r"\d+", doc.xref_get_key(xref, "DescendantFonts")[1]).group())
        doc.xref_set_key(descendant, "BaseFont", "/Unnamed-T3")
        descriptor = int(re.search(r"\d+", doc.xref_get_key(descendant, "FontDescriptor")[1]).group())
        doc.xref_set_key(descriptor, "FontName", "/Unnamed-T3")
        doc.xref_set_key(descriptor, "Flags", "32")


def unnamed_font_pdf(directory: Path, name: str = "unnamed_font.pdf") -> Path:
    """A 16:9 page like Canva's "Урок 1": "Спікер" regular and "Марія
    Пальчук" bold in one text span, both fonts called "Unnamed-T3" and
    neither marked bold anywhere."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=1440, height=810)
    page.insert_font(fontname="F1", fontbuffer=_weightless(DEJAVU))
    page.insert_font(fontname="F2", fontbuffer=_weightless(DEJAVU_BOLD))
    page.insert_text((100, 200), "Спікер ", fontsize=40, fontname="F1")
    x = 100 + fitz.Font(fontfile=DEJAVU).text_length("Спікер ", fontsize=40)
    page.insert_text((x, 200), CANVA_BOLD_NAME, fontsize=40, fontname="F2")
    _unname_fonts(doc, page)
    path = directory / name
    doc.save(str(path))
    doc.close()
    return path


LESSON_TITLE = "БРЕНД-МЕНЕДЖМЕНТ"
LESSON_HIDDEN = "Марія Пальчук"          # a template's leftover, covered by the background
LESSON_SPEAKER = "Оленка Сергієнко"
LESSON_BLOCK = (110, 250, 410, 350)       # orange block with its narrow bold text inside
LESSON_BLOCK_TEXT = "Стратегічне планування"
LESSON_LOGO = (101, 106, 229, 124)        # six dots close together: one logo
LESSON_PHOTO = (900, 250, 1230, 600)
LESSON_LINE = (110, 690, 310, 705)        # a dark bar under the text
LESSON_ICON = (700, 380, 760, 430)         # an icon right in the middle of the slide
LESSON_BADGE = ((1380, 90), 70)            # a grey circle on the card's corner (centre, radius)
LESSON_PHONES = [(100, 120, 400, 690), (570, 120, 870, 690), (1040, 120, 1340, 690)]
LESSON_PHONE_TEXT = "Followers"
LESSON_LIST = ["Довіра. Інфлюенсери мають довіру", "своєї аудиторії, що робить", "рекламу менш нав'язливою.",
               "Охоплення та сегментація.", "Автентичність контенту,", "який виглядає природно.",
               "Креатив. Отримання якісного", "контенту від професіонала."]     # one block of eight lines
LESSON_BIG_SHOT = (81, 123, 1359, 686)   # a browser screenshot over 60% of a slide
LESSON_CAPTION = "Маркетинг"              # under a picture cropped above it (slide 5 of Lesson 1)
LESSON_PANEL = (729, -12, 1466, 843)      # a teal panel over half the slide
LESSON_SIDE_PHOTO = (34, 540, 722, 790)  # a photo 7 pt from the panel
LESSON_SPACED = "та лояльною аудиторією"   # its space alone is underlined (a stray Canva underline)
LESSON_URL = ["https://docs.google.com/sprea", "dsheets/d/12CcHx2U0TgeUTgh", "hHU/edit?usp=sharing"]


def _png(img) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def canva_lesson_pdf(directory: Path, name: str = "lesson.pdf") -> Path:
    """Three 16:9 slides built the way Canva exports a lesson deck (fonts
    "Unnamed-T3"):
    1. a teal textured background image over a leftover name, a white card,
       a logo of small vector dots, a photo, a dark bar, an orange block with
       narrow bold text, a title and the speaker's name;
    2. no text at all: three phone screenshots (with words in the pixels);
    3. a link in several lines, underlined;
    4. no text: one big browser screenshot and a logo;
    5. no text: a teal panel over the right half with dots, a photo next to it."""
    import random

    import fitz
    from PIL import Image, ImageDraw
    rnd = random.Random(7)
    doc = fitz.open()

    page = doc.new_page(width=1440, height=810)
    page.insert_font(fontname="F1", fontbuffer=_weightless(DEJAVU))
    page.insert_font(fontname="F2", fontbuffer=_weightless(DEJAVU_BOLD))
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    page.insert_text((1000, 760), LESSON_HIDDEN, fontsize=28, fontname="F1")
    texture = Image.new("RGB", (720, 405), (77, 168, 176))
    for _ in range(4000):
        x, y = rnd.randrange(720), rnd.randrange(405)
        texture.putpixel((x, y), (70 + rnd.randrange(20), 160 + rnd.randrange(20), 170 + rnd.randrange(15)))
    page.insert_image(page.rect, stream=_png(texture))
    page.draw_rect(fitz.Rect(81, 72, 1395, 738), color=None, fill=(1, 1, 1), radius=0.03)
    for i in range(6):
        page.draw_circle((110 + i * 22, 115), 9, color=None, fill=(0.05, 0.05, 0.05))
    photo = Image.new("RGB", (330, 350))
    ImageDraw.Draw(photo).rectangle((0, 0, 330, 175), fill=(230, 40, 90))
    ImageDraw.Draw(photo).ellipse((80, 120, 250, 300), fill=(200, 140, 60))
    page.insert_image(fitz.Rect(*LESSON_PHOTO), stream=_png(photo))
    page.draw_rect(fitz.Rect(*LESSON_LINE), color=None, fill=(0.03, 0.31, 0.35))
    page.draw_oval(fitz.Rect(*LESSON_ICON), color=None, fill=(0.9, 0.2, 0.4))
    page.draw_circle(LESSON_BADGE[0], LESSON_BADGE[1], color=None, fill=(0.87, 0.85, 0.83))
    page.draw_rect(fitz.Rect(*LESSON_BLOCK), color=None, fill=(1, 0.45, 0.12), radius=0.2)
    # a narrow font, as Canva's: drawn compressed, it is narrower than Arial Bold
    page.insert_text((125, 310), LESSON_BLOCK_TEXT, fontsize=28, fontname="F2",
                     morph=(fitz.Point(125, 310), fitz.Matrix(0.7, 1.15)))
    page.insert_text((194, 480), LESSON_TITLE, fontsize=60, fontname="F2")
    page.insert_text((500, 420), "\n".join(LESSON_LIST), fontsize=24, fontname="F1")
    page.insert_text((1000, 690), LESSON_SPEAKER, fontsize=28, fontname="F1")
    # the template's name drawn again, visible this time (Lesson 1 has both)
    page.insert_text((1000, 760), LESSON_HIDDEN, fontsize=28, fontname="F1")
    # Canva ends a slide with invisible fills over the card (opacity 0)
    page.draw_rect(fitz.Rect(81, 72, 1395, 738), color=None, fill=(1, 1, 1), fill_opacity=0)
    _unname_fonts(doc, page)

    page = doc.new_page(width=1440, height=810)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    # a phone frame: a square picture, wider than the screen, cropped in Canva
    # to the phone; uncropped it overlaps the next screenshot
    frame = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle((140, 6, 460, 594), 40, outline=(20, 20, 20, 255), width=14)
    for box in LESSON_PHONES:
        shot = Image.new("RGB", (300, 570), (245, 245, 245))
        ImageDraw.Draw(shot).text((30, 60), LESSON_PHONE_TEXT, fill="black", font=_font())
        ImageDraw.Draw(shot).text((30, 160), "2 024", fill="black", font=_font())
        page.insert_image(fitz.Rect(*box), stream=_png(shot))
    framed = fitz.open()
    framed.new_page(width=600, height=600).insert_image(fitz.Rect(0, 0, 600, 600), stream=_png(frame))
    for x0, y0, x1, y1 in LESSON_PHONES:
        mid, half = (x0 + x1) / 2, (y1 - y0 + 12) / 2 * 1.3
        place = fitz.Rect(mid - half, y0 - 6, mid + half, y1 + 6)
        k = 600 / place.width                                     # crop in the frame's own points
        crop = fitz.Rect((x0 - 12 - place.x0) * k, 0, (x1 + 12 - place.x0) * k, 600)
        page.show_pdf_page(fitz.Rect(x0 - 12, place.y0, x1 + 12, place.y1), framed, 0, clip=crop)

    page = doc.new_page(width=1440, height=810)
    page.insert_font(fontname="F1", fontbuffer=_weightless(DEJAVU))
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    page.insert_text((575, 120), "Шаблон списку блогерів:", fontsize=35, fontname="F1")
    page.insert_text((60, 700), LESSON_SPACED, fontsize=30, fontname="F1")
    dejavu = fitz.Font(fontfile=DEJAVU)
    gap = dejavu.text_length("та лояльною", fontsize=30)
    page.draw_rect(fitz.Rect(60 + gap, 704, 60 + gap + dejavu.text_length(" ", fontsize=30), 706),
                   color=None, fill=(0, 0, 0))
    for i, line in enumerate(LESSON_URL):
        y = 200 + i * 42
        page.insert_text((575, y), line, fontsize=35, fontname="F1", color=(0, 0.59, 0.65))
        width = fitz.Font(fontfile=DEJAVU).text_length(line, fontsize=35)
        page.draw_rect(fitz.Rect(575, y + 4, 575 + width, y + 6.5), color=None, fill=(0, 0.59, 0.65))
    _unname_fonts(doc, page)

    page = doc.new_page(width=1440, height=810)
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    shot = Image.new("RGB", (640, 282), (250, 250, 250))
    ImageDraw.Draw(shot).rectangle((20, 30, 420, 240), fill=(40, 60, 90))
    ImageDraw.Draw(shot).text((440, 40), "Views", fill="black", font=_font())
    page.insert_image(fitz.Rect(*LESSON_BIG_SHOT), stream=_png(shot))
    for i in range(6):
        page.draw_circle((1270 + i * 22, 760), 9, color=None, fill=(0.05, 0.05, 0.05))

    page = doc.new_page(width=1440, height=810)
    page.insert_font(fontname="F1", fontbuffer=_weightless(DEJAVU))
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    page.insert_text((40, 400), LESSON_CAPTION, fontsize=30, fontname="F1")
    # a tall picture cropped to its top part: its frame covers the caption,
    # its visible part does not
    tall = fitz.open()
    tall.new_page(width=344, height=400).insert_image(fitz.Rect(0, 0, 344, 400),
                                                      stream=_png(Image.new("RGB", (344, 400), (200, 40, 40))))
    page.show_pdf_page(fitz.Rect(34, 20, 378, 420), tall, 0, clip=fitz.Rect(0, 0, 344, 200))
    page.draw_rect(fitz.Rect(*LESSON_PANEL), color=None, fill=(0.22, 0.51, 0.56))
    for i in range(5):
        page.draw_circle((800, 115 + i * 66), 10, color=None, fill=(1, 1, 1))
    side = Image.new("RGB", (344, 125), (200, 160, 120))
    ImageDraw.Draw(side).ellipse((60, 10, 280, 115), fill=(90, 60, 40))
    page.insert_image(fitz.Rect(*LESSON_SIDE_PHOTO), stream=_png(side))

    path = directory / name
    doc.save(str(path))
    doc.close()
    return path


DEJAVU_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
DEJAVU_SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
# Slide 1 of notebook_slides_pdf, in points of its 1376 x 768 pages
NOTE_TITLE = "Розробка бізнес-моделі"            # bold serif, red
NOTE_LOGO = (40, 30, 130, 120)                  # four black diamonds
NOTE_ICON = (1230, 40, 1320, 130)               # a target: three rings
NOTE_RULE = (40, 220, 900, 224)                 # a thin red line under the title
NOTE_BOX = (700, 590, 1320, 720)                # an orange box with regular serif text
NOTE_BOX_TEXT = "Підготував студент групи"
NOTE_TABLE = (40, 290, 1320, 530)               # three columns, a header row
NOTE_COLUMNS = (40, 470, 900, 1320)             # x of the table's vertical lines
NOTE_HEADER = ["Проблема клієнта", "Альтернативи", "Недоліки"]           # bold serif
NOTE_CELLS = ["Незручність і витрати", "Цифрові необанки", "Обмежена мережа"]  # regular serif
# Slide 2: the same in a sans font
NOTE_SANS_TITLE = "Канали комунікації"           # bold sans
NOTE_SANS_BODY = "Цифрова молодь та фахівці"      # regular sans
NOTE_HYPHENED = "Схема бізнес-моделі"              # bold sans; Tesseract is only 81% sure of its second word
NOTE_ARROW = (600, 400, 680, 520)                # a red chevron
NOTE_BUTTON = (900, 400, 1200, 460)              # an orange button with white text
NOTE_BUTTON_TEXT = "КОНФЕРЕНЦІЇ"


def notebook_slides_pdf(directory: Path, name: str = "notebook.pdf") -> Path:
    """Two 16:9 slides that are only pictures, as NotebookLM / Gemini export
    them: a white page, nothing like Canva's colours or fonts.
    1. A serif deck: a logo of diamonds, a bold red title over a thin rule, a
       target icon, a table with vertical lines whose cells' text comes
       within a few points of the next cell's, an orange box with text.
    2. A sans deck: a bold title, regular text, a red chevron, an orange
       button with white bold text on the white page."""
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    k = 2                                       # pixels per point
    doc = fitz.open()

    def font(path, pt):
        return ImageFont.truetype(path, pt * k)

    def put(img):
        page = doc.new_page(width=1376, height=768)
        page.insert_image(page.rect, stream=_png(img))

    img = Image.new("RGB", (1376 * k, 768 * k), "white")
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = NOTE_LOGO
    half = (x1 - x0) / 4
    for cx, cy in ((x0 + half, y0 + half), (x1 - half, y0 + half), (x0 + half, y1 - half), (x1 - half, y1 - half)):
        d.polygon([(k * (cx - half), k * cy), (k * cx, k * (cy - half)), (k * (cx + half), k * cy),
                   (k * cx, k * (cy + half))], fill="black")
    d.text((k * 40, k * 140), NOTE_TITLE, font=font(DEJAVU_SERIF_BOLD, 44), fill=(170, 11, 10))
    d.rectangle([k * v for v in NOTE_RULE], fill=(170, 11, 10))
    x0, y0, x1, y1 = NOTE_ICON
    for n, r in enumerate((45, 30, 15)):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        d.ellipse([k * (cx - r), k * (cy - r), k * (cx + r), k * (cy + r)],
                  fill=(170, 11, 10) if n % 2 == 0 else "white")
    x0, y0, x1, y1 = NOTE_TABLE
    d.rectangle([k * x0, k * y0, k * x1, k * y1], outline="black", width=2 * k)
    d.rectangle([k * x0, k * 370, k * x1, k * 372], fill="black")
    for x in NOTE_COLUMNS[1:-1]:
        d.rectangle([k * x, k * y0, k * (x + 2), k * y1], fill="black")
    for n, (head, cell) in enumerate(zip(NOTE_HEADER, NOTE_CELLS)):
        d.text((k * (NOTE_COLUMNS[n] + 10), k * 315), head, font=font(DEJAVU_SERIF_BOLD, 26), fill="black")
        body = font(DEJAVU_SERIF, 26)
        x = NOTE_COLUMNS[n] + 10
        if n == 0:          # the first cell's text ends 8 pt before the line
            x = NOTE_COLUMNS[1] - 8 - d.textlength(cell, font=body) / k
        d.text((k * x, k * 420), cell, font=body, fill="black")
    d.rectangle([k * v for v in NOTE_BOX], fill=(250, 220, 195))
    d.text((k * (NOTE_BOX[0] + 30), k * (NOTE_BOX[1] + 45)), NOTE_BOX_TEXT, font=font(DEJAVU_SERIF, 26), fill="black")
    put(img)

    img = Image.new("RGB", (1376 * k, 768 * k), "white")
    d = ImageDraw.Draw(img)
    d.text((k * 40, k * 60), NOTE_SANS_TITLE, font=font(DEJAVU_BOLD, 44), fill="black")
    d.text((k * 40, k * 220), NOTE_SANS_BODY, font=font(DEJAVU, 28), fill="black")
    d.text((k * 40, k * 120), NOTE_HYPHENED, font=font(DEJAVU_BOLD, 44), fill="black")
    x0, y0, x1, y1 = NOTE_ARROW
    d.polygon([(k * x0, k * y0), (k * (x0 + 30), k * y0), (k * x1, k * (y0 + y1) / 2),
               (k * (x0 + 30), k * y1), (k * x0, k * y1), (k * (x1 - 30), k * (y0 + y1) / 2)], fill=(200, 16, 46))
    d.rounded_rectangle([k * v for v in NOTE_BUTTON], radius=8 * k, fill=(253, 135, 53))
    d.text((k * (NOTE_BUTTON[0] + 40), k * (NOTE_BUTTON[1] + 14)), NOTE_BUTTON_TEXT, font=font(DEJAVU_BOLD, 26),
           fill="white")
    put(img)

    path = directory / name
    doc.save(str(path))
    doc.close()
    return path


def background_pdf(directory: Path, name: str = "background.pdf") -> Path:
    """A page covered by a picture with a line of real text on top."""
    import fitz
    from PIL import Image
    png = directory / (name + ".png")
    Image.new("RGB", (595, 842), (230, 240, 255)).save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, filename=str(png))
    page.insert_text((72, 100), "Text over a background picture", fontsize=14)
    doc.save(str(path))
    doc.close()
    png.unlink()
    return path


def docx(directory: Path, name: str = "doc.docx", text: str = DOCX_TEXT) -> Path:
    from docx import Document
    path = directory / name
    d = Document()
    d.add_heading("Document heading", level=1)
    d.add_paragraph(text)
    d.save(str(path))
    return path


def pptx(directory: Path, name: str = "deck.pptx", title: str = PPTX_TITLE) -> Path:
    from pptx import Presentation
    path = directory / name
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = "Bullet point body"
    prs.save(str(path))
    return path


def epub(directory: Path, name: str = "book.epub", title: str = EPUB_TITLE, text: str = EPUB_TEXT,
         footnote: str | None = None) -> Path:
    """Minimal valid EPUB 2 built by hand (no pandoc involved). With
    ``footnote`` the chapter gets a [1] reference and a "Notes" section."""
    path = directory / name
    container = (
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>Test Book {title}</dc:title><dc:creator>Test Author</dc:creator>"
        '<dc:language>en</dc:language><dc:identifier id="id">urn:uuid:12345</dc:identifier>'
        "</metadata>"
        '<manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
        '<spine toc="ncx"><itemref idref="ch1"/></spine></package>'
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        '<head><meta name="dtb:uid" content="urn:uuid:12345"/></head>'
        f"<docTitle><text>{title}</text></docTitle>"
        '<navMap><navPoint id="n1" playOrder="1"><navLabel><text>'
        f'{title}</text></navLabel><content src="ch1.xhtml"/></navPoint></navMap></ncx>'
    )
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head>'
        f"<body><h1>{title}</h1><p>{text}"
        + (f'<a href="#n1" id="r1">[1]</a></p><h2>Notes</h2><p id="n1">1. {footnote}</p>' if footnote else "</p>")
        + "</body></html>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        z.writestr("OEBPS/ch1.xhtml", chapter)
    return path


def fb2(directory: Path, name: str = "book.fb2", title: str | None = FB2_TITLE, text: str = FB2_TEXT,
        first: str | None = FB2_AUTHOR_FIRST, last: str | None = FB2_AUTHOR_LAST) -> Path:
    path = directory / name
    author = (f"<first-name>{first}</first-name>" if first else "") + (f"<last-name>{last}</last-name>" if last else "")
    book_title = f"<book-title>{title}</book-title>" if title else ""
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
        'xmlns:l="http://www.w3.org/1999/xlink">'
        "<description><title-info><genre>prose</genre>"
        f"<author>{author}</author>"
        f"{book_title}<lang>en</lang></title-info></description>"
        f"<body><section><title><p>Part One</p></title><p>{text}</p></section></body>"
        "</FictionBook>\n",
        encoding="utf-8",
    )
    return path


def html(directory: Path, name: str = "page.html", text: str = HTML_TEXT) -> Path:
    path = directory / name
    path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Page</title></head>"
        f"<body><div><h1>Page heading</h1><p>{text}</p></div></body></html>",
        encoding="utf-8",
    )
    return path


def telegram_html(directory: Path, name: str = "messages.html", message: str = TELEGRAM_MESSAGE) -> Path:
    path = directory / name
    path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        '<div class="page_wrap"><div class="page_header"><div class="content">'
        f'<div class="text bold">{TELEGRAM_CHAT}</div></div></div>'
        '<div class="page_body chat_page"><div class="history">'
        '<div class="message service" id="message-1"><div class="body details">12 March 2024</div></div>'
        '<div class="message default clearfix" id="message2"><div class="body">'
        '<div class="pull_right date details" title="12.03.2024 10:00:00">10:00</div>'
        f'<div class="from_name">{TELEGRAM_AUTHOR}</div>'
        f'<div class="text">{message}</div></div></div>'
        "</div></div></div></body></html>",
        encoding="utf-8",
    )
    return path


def markdown(directory: Path, name: str = "notes.md", text: str = "Markdown body text") -> Path:
    path = directory / name
    path.write_text(f"# Notes heading\n\n{text} with **bold** word.\n\n- item one\n- item two\n",
                    encoding="utf-8")
    return path


def txt(directory: Path, name: str = "plain.txt", text: str = CYRILLIC_TEXT, encoding: str = "utf-8") -> Path:
    path = directory / name
    path.write_bytes(text.encode(encoding))
    return path


def txt_document(directory: Path, name: str = "doc.txt") -> Path:
    """Plain text with a heading and a list, to exercise TXT -> MD structure detection."""
    path = directory / name
    path.write_text("INTRODUCTION\n\nThis is the first paragraph of the text.\n\n"
                    "- first item\n- second item\n", encoding="utf-8")
    return path


def azw3_renamed_epub(directory: Path, name: str = "book.azw3") -> Path:
    """An EPUB saved with the .azw3 extension (handled by the 'copy' engine)."""
    src = epub(directory, name + ".epub")
    path = directory / name
    shutil.move(src, path)
    return path


def azw3_drm(directory: Path, name: str = "drm.azw3") -> Path:
    path = directory / name
    path.write_bytes(b"\xeaDRMION" + b"\x00" * 200)
    return path


def mobi(directory: Path, name: str = "book.mobi") -> Path:
    """A real MOBI book, built from the EPUB fixture by Calibre."""
    src = epub(directory, name + ".epub")
    path = directory / name
    subprocess.run(["ebook-convert", str(src), str(path)], check=True, capture_output=True, timeout=300)
    src.unlink()
    return path


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, capture_output=True, timeout=120)


def mp4(directory: Path, name: str = "clip.mp4") -> Path:
    path = directory / name
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path))
    return path


def m4a(directory: Path, name: str = "song.m4a") -> Path:
    """One second of AAC audio in an MPEG-4 audio container."""
    path = directory / name
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(path))
    return path


def ts(directory: Path, name: str = "recording.ts", audio: bool = True, video: bool = True,
       vcodec: str = "mpeg2video", acodec: str = "mp2", pix_fmt: str = "yuv420p") -> Path:
    """MPEG transport stream. By default as an older TV recording makes it
    (MPEG-2 video, MP2 audio); IPTV is usually vcodec="libx264", acodec="aac"."""
    path = directory / name
    args: list[str] = []
    if video:
        args += ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=25:duration=1"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    if video:
        # the test pattern is RGB; without -pix_fmt x264 would make 4:4:4,
        # while real recordings are 4:2:0
        args += ["-c:v", vcodec, "-pix_fmt", pix_fmt]
    if audio:
        args += ["-c:a", acodec]
    _ffmpeg(*args, "-shortest", "-f", "mpegts", str(path))
    return path


def webm(directory: Path, name: str = "clip.webm", audio: bool = True, video: bool = True) -> Path:
    path = directory / name
    args: list[str] = []
    if video:
        args += ["-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    if video:
        args += ["-c:v", "libvpx"]
    if audio:
        args += ["-c:a", "libvorbis"]
    _ffmpeg(*args, "-shortest", str(path))
    return path


def zip_members(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.namelist()


def zip_read(data: bytes, member: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(member).decode("utf-8", "replace")


def docx_rich(directory: Path, name: str = "rich.docx", without_pages: bool = False) -> Path:
    """DOCX with a two-run paragraph, a table and a picture. ``without_pages``
    drops <Pages> from docProps/app.xml."""
    from docx import Document
    from PIL import Image
    png = directory / (name + ".png")
    Image.new("RGB", (40, 30), "red").save(png)
    path = directory / name
    d = Document()
    p = d.add_paragraph("Hello ")
    p.add_run("world")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "cell one"
    t.cell(0, 1).text = "cell two"
    d.add_picture(str(png))
    d.save(str(path))
    png.unlink()
    if without_pages:
        import re
        src = path.read_bytes()
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(out, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "docProps/app.xml":
                    data = re.sub(rb"<Pages>\d+</Pages>", b"", data)
                zout.writestr(item, data)
        path.write_bytes(out.getvalue())
    return path
