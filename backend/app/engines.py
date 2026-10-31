"""External converters: pandoc (with Markdown cleanup) and LibreOffice (to PDF)."""
import logging
import os
import subprocess
import uuid

import pypandoc

from app.html_cleanup import prepare_html_for_text
from app.markdown_cleanup import clean_markdown_html, convert_book_footnotes, strip_markdown_data_uris

logger = logging.getLogger(__name__)

def engine_libreoffice(in_path, out_dir, target_ext):
    # Отдельный профиль на каждый запуск: параллельные конвертации иначе
    # дерутся за общий ~/.config/libreoffice и падают.
    profile = f"-env:UserInstallation=file:///tmp/lo_{uuid.uuid4()}"
    proc = subprocess.run(
        ['libreoffice', profile, '--headless', '--convert-to', target_ext,
         in_path, '--outdir', out_dir],
        check=True, capture_output=True, text=True, timeout=300
    )
    out_file = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(in_path))[0]}.{target_ext}")
    # LibreOffice завершается с кодом 0 даже когда нужного фильтра нет,
    # поэтому наличие файла проверяем отдельно.
    if not os.path.exists(out_file):
        raise RuntimeError(
            f"LibreOffice could not convert to {target_ext}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
        )
    return out_file
# =====================================================


# Форматы, которые в PDF умеет только LibreOffice
LIBREOFFICE_PDF_SOURCES = {
    "docx", "doc", "odt", "rtf",
    "pptx", "ppt", "odp",
    "xlsx", "xls", "ods",
    "html", "htm",
}


_PANDOC_TO = {'md': 'gfm', 'txt': 'plain', 'epub': 'epub', 'fb2': 'fb2', 'docx': 'docx'}
_PANDOC_FROM = {'txt': 'markdown', 'md': 'markdown', 'markdown': 'markdown', 'epub': 'epub', 'fb2': 'fb2'}
_BOOKS = ('epub', 'fb2')
_WEB = ('html', 'htm')


def _pandoc_options(source: str, target_format: str) -> tuple[str | None, str, list[str]]:
    """(input format, output format, extra args) for one pandoc run."""
    in_fmt = _PANDOC_FROM.get(source)
    to_fmt = _PANDOC_TO.get(target_format, target_format)
    extra_args: list[str] = []
    # Для EPUB/FB2 -> Markdown используем параметры для сохранения структуры и абзацев
    if target_format == 'md' and source in _BOOKS:
        extra_args = ['--standalone', '--wrap=none', '--strip-comments']
    # HTML -> Markdown: gfm по умолчанию протаскивает <div> в результат как
    # сырую разметку, поэтому расширение raw_html отключаем.
    if target_format == 'md' and source in _WEB:
        to_fmt = 'gfm-raw_html'
        extra_args = ['--wrap=none', '--strip-comments']
    return in_fmt, to_fmt, extra_args


def _clean_markdown_output(out_path: str, source: str, footnotes: bool, footnote_prefix: str) -> None:
    """Pandoc отдает таблицы со сложными ячейками и картинки сырым HTML.
    Для markdown-выхода чистим результат, чтобы в файле не оставалось
    <table>, <colgroup>, <blockquote> и подобных тегов."""
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            produced = f.read()
        cleaned = produced
        # Сноски EPUB/FB2 -> markdown-сноски. Делается ДО общей чистки,
        # пока ссылки на сноски еще можно отличить от обычного текста.
        if footnotes and source in _BOOKS:
            try:
                cleaned = convert_book_footnotes(cleaned, footnote_prefix)
            except Exception as e:
                logger.warning(f"Не удалось преобразовать сноски: {e}")
        cleaned = clean_markdown_html(cleaned)
        # Встроенные base64-картинки (data:-URI) из любого источника:
        # в markdown это только сотни килобайт «символов» вместо текста.
        cleaned = strip_markdown_data_uris(cleaned)
        if cleaned != produced:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
    except Exception as e:
        logger.warning(f"Не удалось очистить markdown от HTML: {e}")


def engine_pandoc(in_path, out_path, target_format, source_ext=None,
                  footnotes=True, footnote_prefix=""):
    source = (source_ext or '').lower()
    in_fmt, to_fmt, extra_args = _pandoc_options(source, target_format)

    # Веб-страница -> MD/TXT: сначала убираем base64-картинки, svg-иконки
    # и интерфейс плеера, иначе они попадают в текст (prepare_html_for_text).
    page_tmp = None
    if source in _WEB and target_format in ('md', 'markdown', 'txt'):
        page_tmp = prepare_html_for_text(in_path)
        if page_tmp:
            in_path, in_fmt = page_tmp, 'html'

    try:
        pypandoc.convert_file(in_path, to_fmt, format=in_fmt, outputfile=out_path, extra_args=extra_args)
    finally:
        if page_tmp and os.path.exists(page_tmp):
            os.remove(page_tmp)

    if target_format in ('md', 'markdown'):
        _clean_markdown_output(out_path, source, footnotes, footnote_prefix)
