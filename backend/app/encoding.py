"""Text encoding detection for uploaded TXT/MD/HTML files (UTF-8/16, cp1251, KOI8-U, cp866...)."""
import logging
import re

logger = logging.getLogger(__name__)

# ===========================================================================
# TXT -> MARKDOWN
# ===========================================================================

CANDIDATE_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "cp1251",
    "koi8-u",
    "cp866",
    "cp1252",
    "latin-1",
)

_JUNK = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")

_COMMON_WORDS = frozenset(
    """
    и в не на что с по для это как а но или же от до за из у то все еще был была
    было были при так они она оно мы вы он я его ее их том том числе если тогда
    та що як не для про від над під між цей ця це ці бути був була було які яка
    the and for that with this from you not are was were have has will can
    """.split()
)

_CYR_UPPER = re.compile(r"[\u0410-\u042f\u0400-\u040f]")
_CYR_LOWER = re.compile(r"[\u0430-\u044f\u0450-\u045f]")


def _score_decoding(text: str) -> float:
    if not text:
        return 0.0
    junk = len(_JUNK.findall(text))
    score = 100.0 - (junk / len(text)) * 1000.0

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return score

    cyr = len(_CYRILLIC.findall(text))
    score += (cyr / len(letters)) * 5.0

    upper, lower = len(_CYR_UPPER.findall(text)), len(_CYR_LOWER.findall(text))
    if upper + lower > 20:
        upper_ratio = upper / (upper + lower)
        if upper_ratio > 0.4:
            score -= (upper_ratio - 0.4) * 120.0

    words = re.findall(r"\S+", text)
    if words:
        mixed = sum(
            1 for w in words if _CYRILLIC.search(w) and re.search(r"[A-Za-z]", w)
        )
        score -= (mixed / len(words)) * 60.0

        hits = sum(
            1 for w in words if w.strip(".,;:!?()\"'«»—-").lower() in _COMMON_WORDS
        )
        score += (hits / len(words)) * 80.0

    weird = sum(1 for c in text if 0x80 <= ord(c) <= 0xBF)
    score -= (weird / len(text)) * 200.0
    return score


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    try:
        text = raw.decode("utf-8")
        if not _JUNK.search(text):
            return "utf-8"
    except UnicodeDecodeError:
        pass

    candidates = list(CANDIDATE_ENCODINGS)
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        from_bytes = None
        logger.debug("charset_normalizer is not installed; using built-in candidates only")
    if from_bytes is not None:
        try:
            for match in (from_bytes(raw).best(),):
                if match is not None and match.encoding:
                    candidates.insert(0, match.encoding)
        except Exception:  # third-party detector: any failure just means "no hint"
            logger.exception("charset_normalizer failed; using built-in candidates only")

    best_enc, best_score = "utf-8", float("-inf")
    sample = raw[:200_000]
    for enc in candidates:
        try:
            score = _score_decoding(sample.decode(enc))
        except (UnicodeDecodeError, LookupError):
            continue
        if score > best_score:
            best_enc, best_score = enc, score
    return best_enc


def read_text_file(path: str):
    with open(path, "rb") as f:
        raw = f.read()
    enc = detect_encoding(raw)
    try:
        text = raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        enc = "utf-8"
        text = raw.decode("utf-8", errors="replace")
    return text, enc
