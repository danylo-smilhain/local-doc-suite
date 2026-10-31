"""Repair of broken PDF text layers (ToUnicode CMaps, glyph names) and text normalization."""
import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# ===========================================================================
# PDF -> TXT/MD: починка текстового слоя
# ===========================================================================
# В некоторых PDF (например, верстка InDesign со шрифтами PetersburgC)
# ToUnicode-карта шрифта сопоставляет одному глифу сразу ДВА символа:
#     <0D> <0020002E>   (глиф /space  -> " .")
#     <1F> <0020002E>   (глиф /period -> " .")
# Старые PyMuPDF (< 1.24) честно отдают " ." на каждый пробел и каждую
# точку, отсюда «Продажи .любят .не .все . .Многие». Новые версии частично
# маскируют это за счет /ActualText, но полагаться на версию библиотеки
# нельзя, поэтому перед извлечением ToUnicode чинится по именам глифов из
# /Encoding /Differences — они в таком PDF верные.

_AGL_NAMES = {
    "space": " ", "nbspace": " ", "period": ".", "comma": ",", "colon": ":",
    "semicolon": ";", "exclam": "!", "question": "?", "hyphen": "-",
    "endash": "\u2013", "emdash": "\u2014", "ellipsis": "\u2026",
    "quotedbl": '"', "quotesingle": "'", "quoteleft": "\u2018",
    "quoteright": "\u2019", "quotedblleft": "\u201c", "quotedblright": "\u201d",
    "quotedblbase": "\u201e", "guillemotleft": "\u00ab", "guillemotright": "\u00bb",
    "parenleft": "(", "parenright": ")", "bracketleft": "[", "bracketright": "]",
    "braceleft": "{", "braceright": "}", "slash": "/", "backslash": "\\",
    "percent": "%", "asterisk": "*", "plus": "+", "equal": "=", "at": "@",
    "numbersign": "#", "ampersand": "&", "underscore": "_", "bar": "|",
    "less": "<", "greater": ">", "dollar": "$", "copyright": "\u00a9",
    "registered": "\u00ae", "degree": "\u00b0", "multiply": "\u00d7",
    "bullet": "\u2022", "numero": "\u2116", "afii61352": "\u2116",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
# afii10017..afii10097 — кириллица (Adobe Glyph List)
_AFII_CYR = {
    **{f"afii{10017 + i}": chr(0x0410 + i) for i in range(6)},   # А..Е
    "afii10023": "\u0401",                                       # Ё
    **{f"afii{10024 + i}": chr(0x0416 + i) for i in range(26)},  # Ж..Я
    **{f"afii{10065 + i}": chr(0x0430 + i) for i in range(6)},   # а..е
    "afii10071": "\u0451",                                       # ё
    **{f"afii{10072 + i}": chr(0x0436 + i) for i in range(26)},  # ж..я
    "afii10053": "\u0404", "afii10055": "\u0406", "afii10056": "\u0407",
    "afii10050": "\u0490", "afii10101": "\u0454", "afii10103": "\u0456",
    "afii10104": "\u0457", "afii10098": "\u0491",
}


def _glyph_to_unicode(name: str):
    if not name:
        return None
    name = name.split(".")[0]
    if name in _AGL_NAMES:
        return _AGL_NAMES[name]
    if name in _AFII_CYR:
        return _AFII_CYR[name]
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4})", name) or re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return None
    if len(name) == 1 and name.isalpha():
        return name
    return None


def _parse_differences(doc, font_obj: str) -> dict:
    """Код символа -> имя глифа из /Encoding /Differences."""
    enc = font_obj
    m = re.search(r"/Encoding\s+(\d+)\s+0\s+R", font_obj)
    if m:
        try:
            enc = doc.xref_object(int(m.group(1)))
        except Exception:
            logger.debug("Suppressed error in _parse_differences()", exc_info=True)
            return {}
    m = re.search(r"/Differences\s*\[(.*?)\]", enc, re.S)
    if not m:
        return {}
    result, code = {}, None
    for tok in re.findall(r"/[^\s/\[\]]+|\d+", m.group(1)):
        if tok.startswith("/"):
            if code is not None:
                result[code] = tok[1:]
                code += 1
        else:
            code = int(tok)
    return result


def _hex_to_text(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-16-be", errors="replace")
    except ValueError:
        return ""


def _is_broken_mapping(text: str) -> bool:
    """Один глиф -> несколько символов, среди которых пробел/пунктуация
    ("\u0020." и т.п.). Настоящие лигатуры (fi, ffl) из букв не трогаем."""
    if len(text) < 2:
        return False
    return any(c.isspace() for c in text) or not any(c.isalnum() for c in text)


def repair_pdf_tounicode(doc) -> int:
    """Чинит битые записи ToUnicode прямо в открытом документе (в памяти,
    файл на диске не меняется). Возвращает число исправленных записей."""
    fixed_total = 0
    seen = set()
    try:
        xref_len = doc.xref_length()
    except Exception:
        logger.debug("Suppressed error in repair_pdf_tounicode()", exc_info=True)
        return 0
    for xref in range(1, xref_len):
        try:
            obj = doc.xref_object(xref)
        except Exception:
            logger.debug("Suppressed error in repair_pdf_tounicode()", exc_info=True)
            continue
        if "/ToUnicode" not in obj or "/Font" not in obj:
            continue
        m = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", obj)
        if not m:
            continue
        cmap_xref = int(m.group(1))
        if cmap_xref in seen:
            continue
        try:
            cmap = doc.xref_stream(cmap_xref).decode("latin-1")
        except Exception:
            logger.debug("Suppressed error in repair_pdf_tounicode()", exc_info=True)
            continue
        diffs = _parse_differences(doc, obj)
        fixed = 0

        def fix_entry(mt):
            nonlocal fixed
            src_hex, dst_hex = mt.group(1), mt.group(2)
            dst = _hex_to_text(dst_hex)
            if not _is_broken_mapping(dst):
                return mt.group(0)
            good = _glyph_to_unicode(diffs.get(int(src_hex, 16)))
            if good is None:
                # Имени глифа нет — оставляем единственный значимый символ.
                stripped = "".join(c for c in dst if not c.isspace())
                good = stripped[:1] if len(stripped) == 1 else " "
            fixed += 1
            return f"<{src_hex}> <{good.encode('utf-16-be').hex().upper()}>"

        def fix_block(mb):
            return re.sub(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", fix_entry, mb.group(0))

        new_cmap = re.sub(r"beginbfchar.*?endbfchar", fix_block, cmap, flags=re.S)
        seen.add(cmap_xref)
        if fixed:
            try:
                doc.update_stream(cmap_xref, new_cmap.encode("latin-1"))
                fixed_total += fixed
            except Exception as e:
                logger.warning(f"Не удалось починить ToUnicode (xref {cmap_xref}): {e}")
    return fixed_total


_PDF_SPACES = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_SPACE_DOT_WORD = re.compile(r" \.(?=[^\W\d_])")
_SPACE_DOT_END = re.compile(r" \.(?=[\s,;:!?»)\"']|$)", re.M)


def normalize_pdf_text(text: str) -> str:
    """Убирает мусор текстового слоя PDF: \ufffd, мягкие переносы,
    неразрывные пробелы, управляющие символы и символы из private use
    (Wingdings и т.п.), а также остатки артефакта « .»."""
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Мягкий перенос в конце строки склеивает слово: «из\xad\nнурительной».
    # Мягкий перенос в самом конце блока превращаем в обычный дефис —
    # склейку со следующим блоком делает extract_pdf_with_ocr.
    text = re.sub(r"\u00ad\s*$", "-", text)
    text = re.sub(r"\u00ad[ \t]*\n[ \t]*", "", text)
    text = text.replace("\u00ad", "")
    # «пись- \n менной»: пробел после переноса мешает склейке слова дальше.
    text = re.sub(r"(\w)-[ \t]+\n", r"\1-\n", text)
    text = text.replace("\ufffd", " ")
    text = _PDF_SPACES.sub(" ", text)
    text = "".join(
        c for c in text
        if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs", "Cn")
    )
    # Страховка на случай, если ToUnicode починить не удалось: каждое
    # « .» — это один глиф (пробел или точка). Включаем только при явной
    # массовости, чтобы не трогать нормальный текст.
    words = len(text.split()) or 1
    if len(_SPACE_DOT_WORD.findall(text)) / words > 0.2:
        text = _SPACE_DOT_WORD.sub(" ", text)
        text = _SPACE_DOT_END.sub(".", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text
