"""Building blocks for merging several uploads into one file."""
import logging
import os
import shutil
import uuid

from pypdf import PdfWriter

from app.config import OUTPUT_DIR
from app.ebooks.epub import epub_to_pdf
from app.encoding import read_text_file
from app.engines import LIBREOFFICE_PDF_SOURCES, engine_libreoffice, engine_pandoc
from app.ocr import extract_pdf_text_cached
from app.telegram import is_telegram_export, telegram_html_to_md
from app.txt import convert_txt_to_md

logger = logging.getLogger(__name__)

_WEB = ('html', 'htm')


def _pdf_as_text(in_path: str, target_ext: str) -> str:
    # pandoc PDF не читает: при слиянии PDF -> MD/TXT берем тот же
    # извлекатель (с OCR сканов), что и при одиночной конвертации.
    text = extract_pdf_text_cached(in_path)
    if target_ext == 'md':
        text = convert_txt_to_md(text, smart=True)
    return text.strip()


def _telegram_as_md(in_path: str, first: bool) -> str | None:
    """Markdown of a Telegram export, ``None`` for any other web page."""
    html_text, _ = read_text_file(in_path)
    if not is_telegram_export(html_text):
        return None
    # Заголовок чата берем только из первого файла экспорта
    return telegram_html_to_md(html_text, with_title=first).strip()


def _pandoc_as_text(in_path: str, source_ext: str, target_ext: str, part_no: int | None) -> str:
    tmp_out = os.path.join(OUTPUT_DIR, f"part_{uuid.uuid4()}.{target_ext}")
    try:
        # При слиянии нескольких книг метки сносок делаем уникальными.
        prefix = f"b{part_no}-" if part_no else ""
        engine_pandoc(in_path, tmp_out, target_ext, source_ext, footnote_prefix=prefix)
        with open(tmp_out, 'r', encoding='utf-8') as f:
            return f.read().strip()
    finally:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)


def _same_text_format(source_ext: str, target_ext: str) -> bool:
    """The source can be copied as is (.htm counts as HTML)."""
    return source_ext == target_ext or (source_ext in _WEB and target_ext == 'html')


def convert_to_text_format(in_path: str, source_ext: str, target_ext: str,
                           first: bool = True, part_no: int = None) -> str:
    """Один файл -> текст в целевом формате (txt/md/html).

    Нужен для слияния: склеивать исходники «как есть» можно только когда
    формат источника совпадает с целевым.
    """
    source_ext = (source_ext or '').lower()
    if source_ext == 'pdf' and target_ext in ('txt', 'md'):
        return _pdf_as_text(in_path, target_ext)
    if source_ext in _WEB and target_ext == 'md':
        telegram = _telegram_as_md(in_path, first)
        if telegram is not None:
            return telegram
    if _same_text_format(source_ext, target_ext):
        text, _ = read_text_file(in_path)
        return text.strip()
    return _pandoc_as_text(in_path, source_ext, target_ext, part_no)

def _remove_all(paths) -> None:
    for tmp in paths:
        if os.path.exists(tmp):
            os.remove(tmp)


def _telegram_to_pdf(texts: list[str], out_path: str) -> None:
    md_parts = [telegram_html_to_md(t, with_title=(i == 0)).strip() for i, t in enumerate(texts)]
    tmp_md = os.path.join(OUTPUT_DIR, f"merge_{uuid.uuid4()}.md")
    tmp_docx = os.path.join(OUTPUT_DIR, f"merge_{uuid.uuid4()}.docx")
    try:
        with open(tmp_md, 'w', encoding='utf-8', newline='\n') as f:
            f.write("\n\n".join(x for x in md_parts if x) + "\n")
        engine_pandoc(tmp_md, tmp_docx, 'docx', 'md')
        pdf_res = engine_libreoffice(tmp_docx, OUTPUT_DIR, 'pdf')
        shutil.move(pdf_res, out_path)
    finally:
        _remove_all((tmp_md, tmp_docx))


def _part_to_pdf(path: str, source_ext: str, tmp_files: list[str]) -> str:
    """One input as a PDF part; every file it creates is listed in tmp_files."""
    if source_ext in LIBREOFFICE_PDF_SOURCES:
        part = engine_libreoffice(path, OUTPUT_DIR, 'pdf')
    elif source_ext == 'epub':
        part = os.path.join(OUTPUT_DIR, f"part_{uuid.uuid4()}.pdf")
        epub_to_pdf(path, part)
    else:
        tmp_docx = os.path.join(OUTPUT_DIR, f"part_{uuid.uuid4()}.docx")
        tmp_files.append(tmp_docx)
        engine_pandoc(path, tmp_docx, 'docx', source_ext)
        part = engine_libreoffice(tmp_docx, OUTPUT_DIR, 'pdf')
    tmp_files.append(part)
    return part


def merge_to_pdf(input_paths, source_ext, out_path):
    """Слияние нескольких файлов в один PDF.

    Экспорт Telegram идет через Markdown -> DOCX: LibreOffice тянет стили из
    css/style.css, которого рядом нет, и рендерит нечитаемую простыню.
    Остальное конвертируется постранично и склеивается PdfWriter.
    """
    source_ext = (source_ext or '').lower()

    if source_ext in _WEB:
        texts = [read_text_file(p)[0] for p in input_paths]
        if texts and all(is_telegram_export(t) for t in texts):
            _telegram_to_pdf(texts, out_path)
            return

    merger = PdfWriter()
    tmp_files: list[str] = []
    try:
        for p in input_paths:
            merger.append(_part_to_pdf(p, source_ext, tmp_files))
        merger.write(out_path)
    finally:
        merger.close()
        _remove_all(tmp_files)
