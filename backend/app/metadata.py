"""Metadata shown after upload and conversion (size, pages, words, images, duration)."""
import logging
import os
import re
import zipfile

import fitz
from docx import Document
from pptx import Presentation

from app.ebooks.azw3 import azw3_epub_cached
from app.encoding import read_text_file
from app.media import ffprobe_duration
from app.ooxml import W

logger = logging.getLogger(__name__)

def _pdf_meta(filepath: str, meta: dict) -> None:
    doc = fitz.open(filepath)
    meta["pages"] = doc.page_count
    text = "".join([page.get_text() for page in doc])
    meta["words"] = len(text.split())
    meta["chars"] = len(text)
    meta["images"] = sum([len(page.get_images(full=True)) for page in doc])
    # Скан без текстового слоя: слова появятся только после OCR,
    # «0» в интерфейсе выглядит как ошибка.
    if meta["words"] == 0 and meta["images"]:
        meta["words"] = "N/A (scan, OCR on convert)"
        meta["chars"] = "N/A"
        meta["scanned"] = True


def _text_meta(filepath: str, meta: dict) -> None:
    text, encoding = read_text_file(filepath)
    meta["words"] = len(text.split())
    meta["chars"] = len(text)
    meta["encoding"] = encoding


def _docx_app_pages(filepath: str) -> int:
    """<Pages> from docProps/app.xml, 0 when missing or unreadable."""
    try:
        with zipfile.ZipFile(filepath) as z:
            app_xml = z.read('docProps/app.xml').decode('utf-8', 'ignore')
        m = re.search(r'<Pages>(\d+)</Pages>', app_xml)
        return int(m.group(1)) if m else 0
    except Exception:
        logger.debug("Suppressed error in get_metadata()", exc_info=True)
        return 0


def _docx_meta(filepath: str, meta: dict) -> None:
    doc = Document(filepath)
    text = " ".join([p.text for p in doc.paragraphs])
    meta["words"] = len(text.split())
    meta["chars"] = len(text)
    # inline_shapes не видит плавающие (anchor) картинки — считаем
    # все рисунки-изображения в теле документа.
    body = doc.element.body
    meta["images"] = sum(1 for _ in body.iter(
        '{http://schemas.openxmlformats.org/drawingml/2006/main}blip'))
    pages = _docx_app_pages(filepath)
    if pages <= 1:
        pages = len(doc.sections) if len(doc.sections) > 1 else pages
    if pages:
        meta["pages"] = pages
    # текст надписей (текстовых полей) тоже считаем
    txbx = " ".join(t.text or "" for t in body.iter(W + 't'))
    if len(txbx.split()) > meta["words"]:
        meta["words"] = len(txbx.split())
        meta["chars"] = len(txbx)


def _pptx_meta(filepath: str, meta: dict) -> None:
    meta["pages"] = len(Presentation(filepath).slides)


def _markup_counts(raw: str) -> tuple[int, int]:
    clean = re.sub(r'<[^>]+>', ' ', raw)
    return len(clean.split()), len(clean)


def _epub_meta(filepath: str, meta: dict) -> None:
    words = 0
    chars = 0
    with zipfile.ZipFile(filepath, 'r') as z:
        for name in z.namelist():
            if name.lower().endswith(('.html', '.xhtml', '.htm')):
                w, c = _markup_counts(z.read(name).decode('utf-8', errors='ignore'))
                words += w
                chars += c
    meta["words"] = words
    meta["chars"] = chars


def _azw3_meta(filepath: str, meta: dict) -> None:
    # Считаем по распакованному EPUB (он же кэш для конвертации)
    epub_meta = get_metadata(azw3_epub_cached(filepath), 'epub')
    meta["words"] = epub_meta["words"]
    meta["chars"] = epub_meta["chars"]


def _fb2_meta(filepath: str, meta: dict) -> None:
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        meta["words"], meta["chars"] = _markup_counts(f.read())


def _media_meta(filepath: str, meta: dict) -> None:
    # У видео и аудио показываем длительность. ffprobe_duration сама
    # глотает ошибки, поэтому сбой ffprobe загрузку не ломает.
    duration = ffprobe_duration(filepath)
    if duration is not None:
        meta["duration"] = duration


_READERS = {
    'pdf': _pdf_meta,
    'txt': _text_meta, 'md': _text_meta, 'html': _text_meta,
    'docx': _docx_meta,
    'pptx': _pptx_meta,
    'epub': _epub_meta,
    'azw3': _azw3_meta, 'mobi': _azw3_meta,
    'fb2': _fb2_meta,
    'mp4': _media_meta, 'mp3': _media_meta, 'webm': _media_meta, 'm4a': _media_meta,
}


def get_metadata(filepath: str, ext: str):
    meta = {"size": os.path.getsize(filepath), "pages": "N/A", "words": "N/A", "chars": "N/A", "images": "N/A"}
    reader = _READERS.get(ext)
    try:
        if reader:
            reader(filepath, meta)
    except Exception:  # metadata is optional: a corrupt file must still upload
        logger.exception("Could not read metadata of %s (%s)", filepath, ext)
    return meta
