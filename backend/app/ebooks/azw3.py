"""AZW3 (Kindle KF8) -> EPUB via Calibre or KindleUnpack, with DRM/KFX detection."""
import contextlib
import glob
import io
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid

import pypandoc

from app.config import OUTPUT_DIR
from app.errors import DependencyMissing, EbookInputError, ErrorCode

logger = logging.getLogger(__name__)

# =====================================================


# ============== AZW3 (Kindle KF8) ==============
# AZW3 разбирается в EPUB, а дальше работают уже готовые пути:
#   AZW3 -> EPUB  — сам EPUB;
#   AZW3 -> PDF   — epub_to_pdf (верстка по CSS книги);
#   AZW3 -> MD    — engine_pandoc(epub -> md) со сносками и чисткой HTML.
# Распаковщик: Calibre (ebook-convert), если он есть в системе, иначе
# KindleUnpack из пакета `mobi` (pip install mobi). Файлы с DRM и формат KFX
# не поддерживаются — для них возвращается понятная ошибка, а не 500.

AZW3_TIMEOUT = 600
_AZW3_LOCK = threading.Lock()          # KindleUnpack пишет в stdout и не потокобезопасен
_AZW3_CACHE_LOCKS = {}
_AZW3_CACHE_GUARD = threading.Lock()


def azw3_inspect(path: str) -> str:
    """Проверяет, что файл — Kindle-книга без DRM.
    Возвращает 'mobi' (PalmDB BOOKMOBI) или 'epub' (переименованный EPUB)."""
    with open(path, 'rb') as f:
        head = f.read(128)
        if head[:2] == b'PK':
            return 'epub'
        if head[:4] == b'\xeaDRM':
            raise EbookInputError(ErrorCode.EBOOK_DRM_PROTECTED,
                                  "The file is DRM-protected (KFX/Kindle); only DRM-free books can be converted.")
        if head[:4] == b'CONT':
            raise EbookInputError(ErrorCode.EBOOK_KFX,
                                  "This is a KFX file, not AZW3; save the book as DRM-free AZW3.")
        if len(head) < 86 or head[60:68] not in (b'BOOKMOBI', b'TEXtREAd'):
            raise EbookInputError(ErrorCode.EBOOK_INVALID, "Not a Kindle AZW3/MOBI book, or the file is damaged.")
        # PalmDB: таблица записей начинается с 78-го байта, первая запись —
        # заголовок PalmDOC/MOBI. Поле encryption — 2 байта по смещению 12.
        rec0 = int.from_bytes(head[78:82], 'big')
        f.seek(rec0)
        rec = f.read(16)
    if len(rec) < 14:
        raise EbookInputError(ErrorCode.EBOOK_INVALID, "The AZW3 file is damaged: the book header is missing.")
    if int.from_bytes(rec[12:14], 'big') != 0:
        raise EbookInputError(ErrorCode.EBOOK_DRM_PROTECTED,
                              "The book is DRM-protected; only DRM-free AZW3 files can be converted.")
    return 'mobi'


def _azw3_via_calibre(in_path: str, out_path: str) -> bool:
    exe = shutil.which('ebook-convert')
    if not exe:
        return False
    try:
        subprocess.run([exe, in_path, out_path], check=True, capture_output=True,
                       text=True, timeout=AZW3_TIMEOUT)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.warning(f"ebook-convert не справился, пробуем KindleUnpack: {e}")
        return False


def _azw3_via_kindleunpack(in_path: str, out_path: str):
    try:
        from mobi.kindleunpack import unpackBook
    except ImportError:
        raise DependencyMissing("AZW3 needs the 'mobi' package (pip install mobi) or Calibre (ebook-convert)")
    work = os.path.join(OUTPUT_DIR, f"azw3_{uuid.uuid4()}")
    os.makedirs(work, exist_ok=True)
    try:
        # KindleUnpack ориентируется на расширение файла
        src = os.path.join(work, "book.azw3")
        shutil.copyfile(in_path, src)
        log = io.StringIO()
        try:
            with _AZW3_LOCK, contextlib.redirect_stdout(log):
                unpackBook(src, work, epubver="A")
        except Exception as e:
            logger.debug("Suppressed error in _azw3_via_kindleunpack()", exc_info=True)
            msg = str(e)
            if "encrypt" in msg.lower() or "drm" in msg.lower():
                raise EbookInputError(ErrorCode.EBOOK_DRM_PROTECTED,
                                      "The book is DRM-protected; only DRM-free AZW3 files can be converted.")
            raise RuntimeError(f"Could not unpack AZW3: {msg or type(e).__name__}")

        # KF8 (настоящий AZW3) -> готовый EPUB в mobi8/
        epubs = glob.glob(os.path.join(work, "mobi8", "*.epub"))
        if epubs:
            shutil.move(epubs[0], out_path)
            return
        # Старый MOBI7 под расширением .azw3 -> HTML -> EPUB через pandoc
        html_path = os.path.join(work, "mobi7", "book.html")
        if os.path.exists(html_path):
            extra = ['--resource-path=' + os.path.join(work, "mobi7")]
            opf = os.path.join(work, "mobi7", "content.opf")
            if os.path.exists(opf):
                raw = open(opf, encoding='utf-8', errors='ignore').read()
                for key in ('title', 'creator', 'language'):
                    m = re.search(rf'<dc:{key}[^>]*>(.*?)</dc:{key}>', raw, re.S)
                    if m and m.group(1).strip():
                        name = 'author' if key == 'creator' else ('lang' if key == 'language' else key)
                        extra += ['--metadata', f"{name}={m.group(1).strip()}"]
            pypandoc.convert_file(html_path, 'epub', format='html',
                                  outputfile=out_path, extra_args=extra)
            return
        raise EbookInputError(ErrorCode.EBOOK_INVALID, "No book text was found in the AZW3 file.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def azw3_to_epub(in_path: str, out_path: str) -> str:
    """AZW3 -> EPUB. Возвращает имя использованного движка."""
    kind = azw3_inspect(in_path)
    tmp = f"{out_path}.{uuid.uuid4().hex}.tmp.epub"
    try:
        if kind == 'epub':
            shutil.copyfile(in_path, tmp)
            engine = "copy"
        elif _azw3_via_calibre(in_path, tmp):
            engine = "calibre"
        else:
            _azw3_via_kindleunpack(in_path, tmp)
            engine = "kindleunpack"
        os.replace(tmp, out_path)
        return engine
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def azw3_epub_cached(in_path: str) -> str:
    """EPUB рядом с загруженным AZW3: распаковка делается один раз (при
    загрузке, для метаданных) и переиспользуется всеми конвертациями."""
    cached = os.path.splitext(in_path)[0] + ".azw3.epub"
    with _AZW3_CACHE_GUARD:
        lock = _AZW3_CACHE_LOCKS.setdefault(cached, threading.Lock())
    with lock:
        if not (os.path.exists(cached) and os.path.getmtime(cached) >= os.path.getmtime(in_path)):
            azw3_to_epub(in_path, cached)
    return cached
