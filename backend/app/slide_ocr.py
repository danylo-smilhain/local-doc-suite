"""The words of a slide picture, for PDF -> PPTX with OCR.

A slide is not a document page: coloured letters on coloured shapes, English
words inside Ukrainian text, titles several times the body size. One
Tesseract pass misses some of it, so a slide is read four times, at the same
time: two pictures in two language orders.
- Pictures: the page as it is, and its darkest channel (coloured letters on
  white come out dark: Canva's orange is as bright as its teal in plain
  grey, and white letters on teal are only found there).
- Orders: the one chosen for the document, and the last language first
  (Tesseract reads "CASE" as "САЗЕ" when Ukrainian comes first, but a
  Ukrainian word in white on teal as "R-3axonn?" when English does).
Where passes read the same place, the surer reading wins. Lines are
then built from where the words are, not from either pass's layout.

Glossary: a word is one Tesseract word with its box in pixels; a line is the
words on one baseline with no column gap and no drawn line (a wall: a
table's or a block's edge) between them.
"""
import statistics
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from typing import NamedTuple

import numpy as np
import pytesseract
from PIL import Image, ImageChops

from app.ocr import OCR_CONFIG

# A word OCR is less sure of stays in the slide picture, where it is drawn
# correctly. On the Canva decks every misreading ("KC" for a checkmark,
# "R-3axonn?" for "PR-заходи?", "Soosa" for "Sposa") scored 84 or less, real
# words 85-96. (Word's layout keeps 55: a page of text has no pictures to
# leave a word in.)
MIN_CONF = 85
# A gap between two words wider than this many font sizes is not a space but
# the gap between two columns (a normal space is about a third of one).
COLUMN_GAP_EM = 1.5
# Two readings are of the same place when they share this much of the
# smaller box.
SAME_PLACE = 0.5
# A letter is at least this wide for each unit of the word box height; a
# reading narrower than that for its letters is a thin stroke (a frame edge,
# a rule) that Tesseract took for "ся" or "|".
MIN_LETTER_WIDTH = 0.15
# A table's or a block's edge drawn between two words: a column of the gap
# between them where this share of the line's height differs by more than
# WALL_CONTRAST (0-255) from the gap's own colour. A cell's text that ends a
# few points before the next cell's begins (closer than a column gap) is two
# lines, not one ("Незручність і витрати Цифрові необанки").
WALL_SHARE = 0.8
WALL_CONTRAST = 60
# Only the middle of the gap is looked at, this many font sizes from each
# word: the passes' word boxes are a few pixels off, and the upright of a
# title's last "Д" taken for a line split "БРЕНД МЕНЕДЖМЕНТ".
WALL_MARGIN_EM = 0.1
# Tesseract reads a vertical line next to a word as "|" ("|відділень").
RULE = "|"


class Word(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float


def other_order(lang: str) -> str:
    """The language order of the second pass: the last language first."""
    langs = lang.split("+")
    return "+".join(langs[-1:] + langs[:-1])


def darkest_channel(img: Image.Image) -> Image.Image:
    """Per pixel the darkest of R, G, B: how far it is from white."""
    r, g, b = img.convert("RGB").split()
    return ImageChops.darker(ImageChops.darker(r, g), b)


def read_words(img: Image.Image, lang: str) -> list[Word]:
    data = pytesseract.image_to_data(img, lang=lang, config=OCR_CONFIG, output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        l, t, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        text = (text or "").strip()
        if text and conf >= MIN_CONF and w >= MIN_LETTER_WIDTH * h * len(text):
            word = without_rules(Word(l, t, l + w, t + h, text, conf))
            if word is not None:
                words.append(word)
    return words


def without_rules(word: Word) -> Word | None:
    """A word without the "|" a drawn line next to it was read as; its box
    loses the same share of its width. None: the word was only a line."""
    text = word.text.strip(RULE)
    if not text:
        return None
    if text == word.text:
        return word
    per = (word.x1 - word.x0) / len(word.text)
    lead = len(word.text) - len(word.text.lstrip(RULE))
    trail = len(word.text) - len(word.text.rstrip(RULE))
    return word._replace(x0=word.x0 + lead * per, x1=word.x1 - trail * per, text=text)


def _shared(a: Word, b: Word) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return w * h / smaller if smaller > 0 else 0.0


def best_words(*passes: list[Word]) -> list[Word]:
    """All words of all passes; where readings share a place, the surest."""
    kept: list[Word] = []
    for word in sorted(chain(*passes), key=lambda w: -w.conf):
        if all(_shared(word, k) <= SAME_PLACE for k in kept):
            kept.append(word)
    return kept


def read_slide_words(img: Image.Image, lang: str) -> list[Word]:
    """All passes (Tesseract runs in its own process, so they run at once)."""
    passes = [(picture, order) for picture in (img, darkest_channel(img)) for order in (lang, other_order(lang))]
    with ThreadPoolExecutor(len(passes)) as pool:
        return best_words(*pool.map(lambda p: read_words(*p), passes))


def walled(picture: np.ndarray, last: Word, word: Word) -> bool:
    """Whether a line is drawn between two words of one baseline (picture:
    the slide as an RGB array): a column of the gap between them, over the
    height both words share, that stands out from the gap's colour."""
    margin = WALL_MARGIN_EM * max(last.y1 - last.y0, word.y1 - word.y0) / 0.72
    x0, x1 = int(np.ceil(last.x1 + margin)), int(word.x0 - margin)
    y0, y1 = int(max(last.y0, word.y0)), int(np.ceil(min(last.y1, word.y1)))
    gap = picture[y0:y1, x0:x1].astype(int)
    if gap.size == 0:
        return False
    colour = np.median(gap.reshape(-1, gap.shape[-1]), axis=0)
    differs = np.abs(gap - colour).max(axis=2) > WALL_CONTRAST
    return bool((differs.mean(axis=0) >= WALL_SHARE).any())


def _same_line(last: Word, word: Word, picture: np.ndarray | None) -> bool:
    h_last, h_word = last.y1 - last.y0, word.y1 - word.y0
    overlap = min(last.y1, word.y1) - max(last.y0, word.y0)
    gap = word.x0 - last.x1
    # word box height ~ 0.72 of the font size (as in pdf_layout._ocr_line_run)
    size = max(h_last, h_word) / 0.72
    return (overlap >= 0.5 * min(h_last, h_word) and -0.5 * size <= gap <= COLUMN_GAP_EM * size
            and (picture is None or not walled(picture, last, word)))


def lines_of(words: list[Word], picture: np.ndarray | None = None) -> list[list[Word]]:
    """Words grouped into lines, each left to right, lines top to bottom.
    With the slide's picture (RGB array) a line also ends at a line drawn
    between two words (see walled)."""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.x0, w.y0)):
        line = next((ln for ln in lines if _same_line(ln[-1], word, picture)), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return sorted(lines, key=lambda ln: (statistics.median(w.y0 for w in ln), ln[0].x0))
