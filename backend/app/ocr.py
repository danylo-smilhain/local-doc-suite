"""OCR: deciding which PDF pages need it, Tesseract language choice, text extraction with cache."""
import hashlib
import io
import logging
import os
import re
import threading
import time
import uuid

import fitz
import pytesseract
from PIL import Image

from app.config import OCR_CACHE_DIR
from app.encoding import _CYRILLIC
from app.pdf_text import normalize_pdf_text, repair_pdf_tounicode

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 60

# --- OCR / детекция битого текстового слоя ---
OCR_LANG = "ukr+rus+eng"   # документ трёхъязычный: укр, рос, англ
OCR_DPI = 300
OCR_CONFIG = "--oem 1 --psm 3"
BROKEN_WORD_RATIO = 0.25   # доля «слов»-мусора на странице
BROKEN_PAGE_RATIO = 0.5    # доля битых страниц в документе

def page_is_scan(page) -> bool:
    """Страница-скан: текста нет, но есть растровое изображение.

    Проверка на картинку нужна, чтобы пустые и почти пустые страницы
    обычного текстового PDF не засчитывались как сканы.
    """
    if len(page.get_text("text").strip()) >= MIN_TEXT_CHARS:
        return False
    try:
        return bool(page.get_images())
    except Exception:
        logger.debug("Suppressed error in page_is_scan()", exc_info=True)
        return True

BAD_TOKEN = re.compile(r'^(?=\S*[А-Яа-яІіЇїЄєҐґ])(?=\S*[A-Za-z0-9\[\]{}_\\|~^])\S{3,}$')

def page_text_is_broken(page) -> bool:
    try:
        words = page.get_text("text").split()
    except Exception:
        logger.debug("Suppressed error in page_text_is_broken()", exc_info=True)
        return False
    if len(words) < 10:
        return False
    bad = sum(1 for w in words if BAD_TOKEN.match(w))
    return bad / len(words) > BROKEN_WORD_RATIO

def page_needs_ocr(page) -> bool:
    return page_is_scan(page) or page_text_is_broken(page)

def pdf_text_layer_is_broken(pdf_path: str) -> bool:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        logger.debug("Suppressed error in pdf_text_layer_is_broken()", exc_info=True)
        return False
    try:
        # Считаем и битый текстовый слой, и страницы-сканы.
        # Раньше здесь был только page_text_is_broken, а он возвращает False
        # при len(words) < 10 — то есть у чистого скана «битых» страниц ноль.
        # Такие файлы уходили в pdf2docx, который их не умеет и честно пишет
        # "Words count: 0. It might be a scanned pdf, which is not supported yet",
        # после чего в DOCX попадали только картинки страниц.
        need_ocr = sum(1 for p in doc if page_needs_ocr(p))
        total = doc.page_count
    finally:
        doc.close()
    return total > 0 and need_ocr / total > BROKEN_PAGE_RATIO


# ---------------------------------------------------------------------------
# OCR для PDF -> TXT/MD
# ---------------------------------------------------------------------------
# Раньше extract_pdf_with_ocr отправлял страницу в OCR только по
# page_text_is_broken(), а та возвращает False при < 10 словах. У чистого
# скана (книга «The Politics of Presence», 219 страниц-картинок без
# текстового слоя) слов ноль -> все страницы считались «нормальными»,
# get_text() отдавал пустоту, и Markdown получался пустым. Теперь критерий
# тот же, что и в DOCX-ветке: page_needs_ocr() = скан ИЛИ битый слой.

OCR_TEXT_WORKERS = max(1, min(4, os.cpu_count() or 1))
OCR_LANG_SAMPLE_PAGES = 5
# Для извлечения текста 200 dpi хватает: на сканах ~120 dpi результат
# совпадает с 300 dpi на 99.9%, а страница распознается на ~20% быстрее.
OCR_TEXT_DPI = 200
# Доля латиницы/кириллицы в образцах, при которой документ считается
# одноязычным и чужие модели из OCR убираются.
OCR_MONO_SCRIPT_RATIO = 0.98
# Tesseract внутри себя тоже распараллеливается (OpenMP); при нескольких
# процессах это только мешает.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

_LATIN_RE = re.compile(r"[A-Za-z]")
_PAGE_NUM_RE = re.compile(r"^[\[\(]?\s*(?:\d{1,4}|[ivxlcdm]{1,7})\s*[\]\)]?$", re.I)


def available_ocr_lang(lang: str = OCR_LANG) -> str:
    """Оставляет только установленные языки Tesseract.

    Если в системе нет, например, ukr.traineddata, tesseract падает на
    КАЖДОЙ странице, а ошибка раньше молча глоталась (except: pass) —
    результат тоже был пустым.
    """
    wanted = [l for l in lang.split("+") if l]
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception as e:
        logger.warning(f"Не удалось получить список языков Tesseract: {e}")
        return lang
    usable = [l for l in wanted if l in installed]
    missing = [l for l in wanted if l not in installed]
    if missing:
        logger.warning(f"Языки OCR не установлены и пропущены: {', '.join(missing)}")
    if usable:
        return "+".join(usable)
    fallback = "eng" if "eng" in installed else next(
        (l for l in sorted(installed) if l != "osd"), lang)
    logger.warning(f"Ни один из языков {lang} не установлен, используется {fallback}")
    return fallback


def _render_page_png(page, dpi: int = OCR_TEXT_DPI) -> bytes:
    # Серый вместо RGB: сканы почти всегда ч/б, PNG в разы меньше.
    return page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY).tobytes("png")


def _ocr_png(png: bytes, lang: str, dpi: int = OCR_TEXT_DPI) -> str:
    img = Image.open(io.BytesIO(png))
    return pytesseract.image_to_string(img, lang=lang,
                                       config=f"{OCR_CONFIG} --dpi {dpi}")


def _choose_ocr_lang_order(samples, lang: str) -> str:
    """Ставит язык основной письменности документа первым.

    При порядке «ukr+rus+eng» на английском тексте Tesseract иногда выдает
    кириллические двойники латиницы («СНАРТЕВ» вместо «CHAPTER»). Порядок
    «eng+ukr+rus» этого не дает. Письменность определяем по нескольким
    страницам-образцам.
    """
    parts = lang.split("+")
    if len(parts) < 2:
        return lang
    lat = sum(len(_LATIN_RE.findall(t)) for t in samples)
    cyr = sum(len(_CYRILLIC.findall(t)) for t in samples)
    if lat + cyr < 200:
        return lang
    latin_langs = [l for l in parts if l in ("eng", "deu", "fra", "spa", "ita", "pol", "lat")]
    cyr_langs = [l for l in parts if l in ("ukr", "rus", "bel", "bul", "srp")]
    rest = [l for l in parts if l not in latin_langs and l not in cyr_langs]
    lat_share = lat / (lat + cyr)
    # Одноязычный документ: лишние модели даже вторыми по счету
    # портят мелкий шрифт сносок («ритрозе» вместо «purpose»).
    if lat_share >= OCR_MONO_SCRIPT_RATIO and latin_langs:
        return "+".join(latin_langs)
    if 1 - lat_share >= OCR_MONO_SCRIPT_RATIO and cyr_langs:
        return "+".join(cyr_langs + rest)
    if lat_share > 0.85 and latin_langs:
        return "+".join(latin_langs + cyr_langs + rest)
    if lat_share < 0.15 and cyr_langs:
        return "+".join(cyr_langs + latin_langs + rest)
    return lang


def _norm_header(line: str) -> str:
    return re.sub(r"[\d\W_]+", " ", line.lower()).strip()


def _strip_running_heads(pages_text):
    """Убирает колонтитулы и номера страниц из распознанных страниц.

    На сканах книг первая/последняя строка страницы — «2 From Ideas to
    Presence», «Quotas for Women 61» или просто номер. Если их не убрать,
    они вклеиваются посреди абзацев, а абзац, перешедший на следующую
    страницу, не склеивается.
    """
    def edge_lines(text):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return lines[:2] + lines[-2:] if lines else []

    counts = {}
    for text in pages_text:
        if not text:
            continue
        for key in {_norm_header(l) for l in edge_lines(text)}:
            if key:
                counts[key] = counts.get(key, 0) + 1
    repeated = {k for k, c in counts.items() if c >= 3}

    def is_head(line):
        s = line.strip()
        if not s or len(s) > 80:
            return False
        if _PAGE_NUM_RE.match(s):
            return True
        return _norm_header(s) in repeated and len(_norm_header(s).split()) <= 8

    out = []
    for text in pages_text:
        if not text:
            out.append(text)
            continue
        lines = text.split("\n")
        idx = [i for i, l in enumerate(lines) if l.strip()]
        drop = set()
        for i in idx[:2]:
            if is_head(lines[i]):
                drop.add(i)
            else:
                break
        for i in reversed(idx[-2:]):
            if i in drop:
                break
            if is_head(lines[i]):
                drop.add(i)
            else:
                break
        out.append("\n".join(l for i, l in enumerate(lines) if i not in drop))
    return out


def extract_pdf_with_ocr(in_path, lang: str = OCR_LANG):
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    doc = fitz.open(in_path)
    try:
        repaired = repair_pdf_tounicode(doc)
        if repaired:
            logger.info(f"Исправлено записей ToUnicode: {repaired}")
    except Exception as e:
        logger.warning(f"Проверка ToUnicode не удалась: {e}")

    try:
        # ГЛАВНОЕ ИСПРАВЛЕНИЕ: скан тоже требует OCR, не только битый слой.
        need_ocr = [page_needs_ocr(p) for p in doc]
        ocr_pages = [i for i, n in enumerate(need_ocr) if n]

        ocr_text = {}
        if ocr_pages:
            lang = available_ocr_lang(lang)
            logger.info(f"OCR страниц: {len(ocr_pages)} из {doc.page_count}, языки: {lang}")
            # PyMuPDF не потокобезопасен: рендерим в основном потоке,
            # Tesseract (отдельный процесс) — в пуле потоков.
            with ThreadPoolExecutor(max_workers=OCR_TEXT_WORKERS) as pool:
                if "+" in lang:
                    # Образцы равномерно по документу (пропуская обложку и конец).
                    n = len(ocr_pages)
                    k = min(OCR_LANG_SAMPLE_PAGES, n)
                    sample_idx = sorted({ocr_pages[int(n * (j + 1) / (k + 1))] for j in range(k)})
                    pngs = {i: _render_page_png(doc[i]) for i in sample_idx}
                    futs = {i: pool.submit(_ocr_png, pngs[i], lang) for i in sample_idx}
                    samples = []
                    for i, f in futs.items():
                        try:
                            samples.append(f.result())
                        except Exception as e:
                            logger.warning(f"OCR образца стр. {i + 1}: {e}")
                    new_lang = _choose_ocr_lang_order(samples, lang)
                    if new_lang != lang:
                        logger.info(f"Порядок языков OCR: {lang} -> {new_lang}")
                        lang = new_lang
                    else:
                        # Порядок тот же — образцы уже готовы, не распознаем повторно.
                        ocr_text.update({i: t for i, t in zip(futs, samples)})

                futures, window = {}, OCR_TEXT_WORKERS * 3
                errors = 0
                total = len(ocr_pages)
                progress = {"done": len(ocr_text)}
                progress_lock = threading.Lock()
                t_start = time.time()

                def _report(_f):
                    with progress_lock:
                        progress["done"] += 1
                        done = progress["done"]
                    if done % 10 == 0 or done == total:
                        el = time.time() - t_start
                        logger.info(f"OCR: {done}/{total} стр., {el:.0f} с")
                for i in ocr_pages:
                    if i in ocr_text:
                        continue
                    try:
                        png = _render_page_png(doc[i])
                    except Exception as e:
                        logger.warning(f"Не удалось отрисовать стр. {i + 1}: {e}")
                        continue
                    futures[i] = pool.submit(_ocr_png, png, lang)
                    futures[i].add_done_callback(_report)
                    # Ограничиваем число страниц в памяти.
                    pending = [f for f in futures.values() if not f.done()]
                    if len(pending) >= window:
                        wait(pending, return_when=FIRST_COMPLETED)
                for i, f in futures.items():
                    try:
                        ocr_text[i] = f.result()
                    except Exception as e:
                        errors += 1
                        logger.warning(f"OCR стр. {i + 1} не удался: {e}")
                if errors and errors == len(futures) and not any(ocr_text.values()):
                    raise RuntimeError(
                        "OCR failed on every page. Check that Tesseract and "
                        f"the languages '{lang}' are installed.")

        # Колонтитулы ищем по всем распознанным страницам сразу.
        order = sorted(ocr_text)
        cleaned = _strip_running_heads([normalize_pdf_text(ocr_text[i]) for i in order])
        ocr_text = dict(zip(order, cleaned))

        # Пометка нужна только для смешанных документов, где часть текста
        # взята из слоя, а часть распознана. Для сплошного скана она лишь
        # разрывает абзацы на каждой странице.
        mark_ocr = 0 < len(ocr_pages) < doc.page_count

        raw_blocks = []
        for pno, page in enumerate(doc):
            if not need_ocr[pno]:
                for b in page.get_text("blocks"):
                    if b[6] == 0:
                        txt = normalize_pdf_text(b[4]).strip()
                        if txt:
                            raw_blocks.append(txt)
                continue
            ocr_res = (ocr_text.get(pno) or "").strip()
            if not ocr_res:
                continue
            if mark_ocr:
                raw_blocks.append("[Розпізнано зі сторінки]:")
            for ocr_p in re.split(r'\n\s*\n', ocr_res):
                if ocr_p.strip():
                    raw_blocks.append(ocr_p.strip())
    finally:
        doc.close()

    merged_paragraphs = []
    list_marker_re = re.compile(r'^(\d+(?:\.\d+)*[.)]\s|[*•+]\s)')
    
    for block in raw_blocks:
        block = block.replace("\r\n", "\n").replace("\r", "\n")
        block = block.replace("-\n", "")
        block_lines = block.split('\n')
        processed_block_lines = []
        
        for line in block_lines:
            line = line.strip()
            if not line:
                continue
                
            is_new_paragraph = (
                not processed_block_lines or 
                line.startswith(('-', '–', '—', '−')) or 
                list_marker_re.match(line)
            )
            
            if is_new_paragraph:
                processed_block_lines.append(line)
            else:
                processed_block_lines[-1] += " " + line
                
        if not processed_block_lines:
            continue
            
        processed_block = "\n\n".join(processed_block_lines)
        if (merged_paragraphs and 
            not merged_paragraphs[-1].endswith(('.', '!', '?', ':', ';', '"', '»', '>')) and 
            processed_block[0].islower()):
            prev = merged_paragraphs[-1]
            if re.search(r"[^\W\d_]-$", prev):
                # Перенос слова на границе блоков: «пись-» + «менной».
                merged_paragraphs[-1] = prev[:-1] + processed_block
            else:
                merged_paragraphs[-1] += " " + processed_block
        else:
            merged_paragraphs.append(processed_block)
            
    return "\n\n".join(merged_paragraphs)

_extract_locks = {}
_extract_locks_guard = threading.Lock()
# Меняйте при изменении логики извлечения, чтобы старый кэш не использовался.
EXTRACT_CACHE_VERSION = "1"


def _file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_text_cached(in_path: str, lang: str = OCR_LANG) -> str:
    """extract_pdf_with_ocr с кэшем по содержимому файла.

    OCR большого скана идет минуты. Если браузер или nginx не дождались
    ответа и пользователь нажал кнопку еще раз, раньше распознавание
    запускалось заново — параллельно первому, вдвое медленнее. Теперь
    повторный запрос ждет первый и берет готовый результат из кэша.
    """
    key = f"{_file_sha1(in_path)}_{lang}_{OCR_TEXT_DPI}_v{EXTRACT_CACHE_VERSION}"
    cache_path = os.path.join(OCR_CACHE_DIR, key.replace("+", "-") + ".txt")
    with _extract_locks_guard:
        lock = _extract_locks.setdefault(key, threading.Lock())
    with lock:
        if os.path.exists(cache_path):
            logger.info(f"Текст PDF взят из кэша: {cache_path}")
            with open(cache_path, "r", encoding="utf-8") as f:
                return f.read()
        text = extract_pdf_with_ocr(in_path, lang)
        tmp = cache_path + f".{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, cache_path)
        except Exception as e:
            logger.warning(f"Не удалось записать кэш OCR: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)
        return text
