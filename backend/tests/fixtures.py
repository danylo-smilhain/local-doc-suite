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


def garbled_text_pdf(directory: Path, name: str = "garbled.pdf") -> Path:
    """A 16:9 page whose readable words are a picture (what a viewer shows for
    the broken font) with a garbled text line over it, plus one line of
    normal text."""
    import fitz
    from PIL import Image, ImageDraw
    png = directory / (name + ".png")
    img = Image.new("RGB", (1700, 1200), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(SCANNED_PAGE_LINES):
        draw.text((60, 60 + i * 120), line, fill="black", font=_font())
    img.save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=1440, height=810)
    page.insert_image(fitz.Rect(100, 150, 1100, 750), filename=str(png))
    page.insert_text((100, 80), CLEAN_LINE, fontsize=30)
    # Canva draws the visible letters as vector outlines; a filled square
    # inside the clean line stands for them
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
    img = Image.new("RGB", (1700, 1200), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(SCANNED_PAGE_LINES):
        draw.text((60, 60 + i * 120), line, fill="black", font=_font())
    img.save(png)
    path = directory / name
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(40, 60, 555, 480), filename=str(png))
    doc.save(str(path))
    doc.close()
    png.unlink()
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
