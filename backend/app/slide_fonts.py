"""How the letters of a slide picture look: serif or sans, bold or regular.
Read from the strokes of the letters, for text that has no font to tell it
(OCR of a picture slide, Canva's "Unnamed-T3" fonts), so the text box gets
a font that looks like the one in the picture.

Glossary (all on a word's ink, the pixels of its letters):
- a run: a stretch of ink along a row (or a column);
- the stem: the commonest run along the rows, the width of the uprights;
- the bar: the commonest run down the columns, the thickness of the
  horizontal strokes;
- contrast: stem over bar. A sans font draws both alike (0.9-1.55 measured,
  bold ones included); a serif font makes the uprights thicker (1.76 and up
  in DejaVu Serif, Liberation Serif and Gemini's serif, regular);
- narrowness: a word's width over its text drawn in Helvetica at the same
  height; a condensed font's uprights are thinner by as much while its bars
  are not, so its contrast is taken over its narrowness (a narrow serif on
  Lean Canvas: 0.78 wide, contrast 1.25-1.4, over its width 1.6-1.8);
- feet: the runs along the top and the bottom of the letters' main body
  over the stem; serifs make them longer (1.7 and up) than the uprights;
- the body: the rows of the letters' main body (with at least half the
  fullest row's ink: the x-height), without capitals, ascenders and
  descenders, which a line's crop may cut;
- weight: the stem over the body's height; for a word of capitals or
  digits, which has no x-height (its fullest rows are the bars of Е, Н, Ф
  or of 7), over the height of its uprights: the rows with a third of a
  typical row's ink, without the dots of Ї or the tail of Ц;
- boldness: where a word's weight lies between its own text drawn regular
  (0) and drawn bold (1) in its family (Helvetica or Times), on a log
  scale: bold weighs 1.2 to 2.3 times regular depending on the letters;
- bold: a sans word a third of the way to bold (0.3: Helvetica regular is
  a typical sans regular; DejaVu and Liberation regular reach 0.15, Canva's
  regular -0.15, its semibold starts at 0.44); a serif word two thirds of
  the way (0.67: Times regular is lighter than most serifs', Gemini's
  regular reaches 0.64 ("Віртуальна"), its bold starts at 0.70 ("засади"));
- slant: how far the strokes lean right per pixel of height, found as the
  shear that stands them upright (the sharpest columns of ink); upright
  fonts measure -0.03 to 0.02, italic and oblique 0.14 to 0.20;
- a line's weights: a word within UNSURE of its threshold ("Схема", 0.59
  in a bold title) takes the weight most of its line's other words have;
  a word not measured (too short: "UA", "і", "–") that of its nearest
  measured neighbour, the one after it on a tie; one that closes a phrase
  ("очах ЦА,") goes with what came before it, a dash or a word after a
  phrase's end ("CPA – це", "емоції, а не") with what follows.
"""
import fitz
import numpy as np
from PIL import Image

from app.pdf_layout import _FONT_FAMILIES, _metric_font

# Below this font size in pixels the strokes are a pixel or two and the
# measures are noise (DejaVu Serif read as sans at 30 px): the line stays sans.
MIN_FAMILY_PX = 40
# A line is serif when the median contrast of its words reaches this ...
SERIF_CONTRAST = 1.65
# ... or reaches FOOTED_CONTRAST while the feet are this long: Gemini's bold
# serif has contrast 1.6 but feet 1.8. Regular sans fonts stay under 1.36 in
# contrast (their feet reach 1.99), bold ones under 1.4 in feet.
FOOTED_CONTRAST = 1.4
SERIF_FEET = 1.7
# Words this short say little about their font and are left out of the vote.
MIN_VOTE_LETTERS = 3
# Rows with at least this share of the fullest row's ink are the body (30%
# took the capitals' rows of "Проблема" in some fonts and not in others).
BODY_SHARE = 0.5
CAPS_ROW_SHARE = 0.3
# A boldness above this is a mis-measure (an underline left a body of 7 px:
# 8), and a text whose bold is not this many times as heavy as its regular
# ("KPI" in Helvetica: 0.94) cannot be told: neither votes.
MAX_BOLDNESS = 2.5
MIN_BOLD_GAIN = 1.15
# The boldness from which a word is bold, by family (see the glossary).
# Deciding per page instead (splitting its words into two weights) split
# pages of one weight: 19 of 28 regular words of a Gemini slide came out bold.
BOLD_FROM = {"sans": 0.3, "serif": 0.67}
# A line whose words' median slant reaches this is italic (see the glossary).
ITALIC_SLANT = 0.12
SLANTS = np.arange(-0.1, 0.5, 0.02)
# A word this near its family's threshold is decided by its line.
UNSURE = 0.1
# A contrast below this is a stroke mis-measured (a bar three times a stem):
# that word has no vote on its family.
MIN_CONTRAST = 0.8
# A word is drawn at this many pixels high to compare its weight with.
RENDER_PX = 120


def ink(crop: np.ndarray) -> np.ndarray:
    """The letters of a crop (RGB array) around one word: the pixels at least
    half as far from the crop's edge colour as the farthest one, trimmed."""
    a = crop.astype(int)
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    dist = np.abs(a - np.median(edge, axis=0)).max(axis=2)
    mask = dist >= 0.5 * max(int(dist.max()), 1)
    ys, xs = np.nonzero(mask)
    if not len(xs) or dist.max() == 0:
        return np.zeros((0, 0), bool)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def runs(mask: np.ndarray) -> np.ndarray:
    """Lengths of the ink runs along the rows of a mask."""
    edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    return np.nonzero(edges == -1)[1] - np.nonzero(edges == 1)[1]


def commonest(lengths: np.ndarray) -> float:
    """The commonest run length, refined to a fraction of a pixel by its two
    neighbours; 0 without runs."""
    if not len(lengths):
        return 0.0
    counts = np.bincount(lengths)
    top = int(counts.argmax())
    lo, hi = max(1, top - 1), min(len(counts), top + 2)
    near = counts[lo:hi]
    return float((np.arange(lo, hi) * near).sum() / max(1, near.sum()))


def contrast(mask: np.ndarray) -> float:
    bar = commonest(runs(mask.T))
    return commonest(runs(mask)) / bar if bar else 0.0


def body(mask: np.ndarray) -> np.ndarray:
    """Indexes of the rows of the letters' main body."""
    rows = mask.sum(axis=1)
    return np.nonzero(rows >= BODY_SHARE * rows.max())[0]


def feet(mask: np.ndarray) -> float:
    """Median run along the top and bottom two rows of the body over the stem."""
    stem = commonest(runs(mask))
    if not stem:
        return 0.0
    rows = body(mask)
    edge_rows = mask[[rows.min(), rows.min() + 1, rows.max() - 1, rows.max()]]
    lengths = runs(edge_rows)
    return float(np.median(lengths)) / stem if len(lengths) else 0.0


def no_x_height(text: str) -> bool:
    """Whether a word is all capitals or digits: it has no x-height, and its
    strokes do not tell serif from sans (a sans "КОНФЕРЕНЦІЇ": contrast 2.5)."""
    return any(c.isalnum() for c in text) and not any(c.islower() for c in text)


def body_height(mask: np.ndarray, whole: bool = False) -> int:
    """Height of the body; of a word of capitals (whole) the rows of its
    uprights, which hold at least CAPS_ROW_SHARE of a median row's ink."""
    if whole:
        counts = mask.sum(axis=1)
        rows = np.nonzero(counts >= CAPS_ROW_SHARE * np.median(counts[counts > 0]))[0]
    else:
        rows = body(mask)
    return int(rows.max() - rows.min() + 1)


def weight(mask: np.ndarray, whole: bool = False) -> float:
    return commonest(runs(mask)) / body_height(mask, whole) if mask.any() else 0.0


def narrowness(mask: np.ndarray, text: str) -> float:
    """A word's width over its text drawn in Helvetica at its height, at
    most 1 (a wide font's contrast is not raised)."""
    drawn_text = drawn(text, "sans", False, body_height(mask))
    return min(1.0, mask.shape[1] / drawn_text.shape[1]) if drawn_text.size else 1.0


def family(masks: list[np.ndarray], size_px: float, texts: list[str] | None = None) -> str:
    """"serif" or "sans" for a line, from the ink of its words and, given
    their texts, how narrow they are (see the glossary); too small to tell,
    or nothing to go by: "sans"."""
    if size_px < MIN_FAMILY_PX or not masks:
        return "sans"
    texts = texts or [None] * len(masks)
    measured = [(m, t) for m, t in zip(masks, texts) if contrast(m) >= MIN_CONTRAST]
    if not measured:
        return "sans"
    c = float(np.median([contrast(m) / (narrowness(m, t) if t else 1.0) for m, t in measured]))
    f = float(np.median([feet(m) for m, _ in measured]))
    serif = c >= SERIF_CONTRAST or (c >= FOOTED_CONTRAST and f >= SERIF_FEET)
    return "serif" if serif else "sans"


def slant(mask: np.ndarray) -> float:
    """The slant of a word's strokes (see the glossary)."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return 0.0
    best, at = -1.0, 0.0
    for s in SLANTS:
        x = np.round(xs + s * (ys - mask.shape[0] / 2)).astype(int)
        sharpness = float((np.bincount(x - x.min()).astype(float) ** 2).sum())
        if sharpness > best:
            best, at = sharpness, float(s)
    return at


def italic(masks: list[np.ndarray]) -> bool:
    """Whether a line is italic, from the ink of its words."""
    return bool(masks) and float(np.median([slant(m) for m in masks])) >= ITALIC_SLANT


def drawn(text: str, fam: str, bold: bool, height: int, whole: bool = False) -> np.ndarray:
    """The ink of a text drawn in the family's metric font (Helvetica or
    Times, regular or bold), scaled so that its body (whole: all of it) is
    the given height."""
    font = _metric_font(fam, bold, False)
    doc = fitz.open()
    page = doc.new_page(width=RENDER_PX * (len(text) + 2), height=RENDER_PX * 2)
    writer = fitz.TextWriter(page.rect)
    writer.append((RENDER_PX / 2, RENDER_PX * 1.4), text, font=font, fontsize=RENDER_PX)
    writer.write_text(page)
    pix = page.get_pixmap(alpha=False)
    mask = ink(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3))
    if not mask.any():
        return mask
    k = height / body_height(mask, whole)
    img = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (max(1, round(mask.shape[1] * k)), max(1, round(mask.shape[0] * k))), Image.LANCZOS)
    return np.asarray(img) > 127


def relative_weight(mask: np.ndarray, text: str, fam: str) -> tuple[float, float] | None:
    """(the word's weight, the weight of its text drawn bold), both over the
    weight of its text drawn regular in its family; None: nothing to measure."""
    whole = no_x_height(text)
    own = weight(mask, whole)
    if not own or not text.strip():
        return None
    height = body_height(mask, whole)
    regular = weight(drawn(text, fam, False, height, whole), whole)
    bold = weight(drawn(text, fam, True, height, whole), whole)
    if not regular or not bold:
        return None
    return own / regular, bold / regular


def boldness(measure: tuple[float, float] | None) -> float | None:
    """A relative_weight measure as boldness (see the glossary); None where
    it cannot be told or is out of bounds."""
    if measure is None or measure[1] < MIN_BOLD_GAIN:
        return None
    b = float(np.log(measure[0]) / np.log(measure[1]))
    return b if b <= MAX_BOLDNESS else None


def bold_of(measure: tuple[float, float] | None, fam: str) -> bool | None:
    """Bold or not from relative_weight's measure in a family; None: cannot
    be told."""
    b = boldness(measure)
    return None if b is None else b >= BOLD_FROM[fam]


def is_bold(mask: np.ndarray, text: str, fam: str) -> bool:
    return bool(bold_of(relative_weight(mask, text, fam), fam))


# What ends in one of these ends a phrase (see "a line's weights").
CLOSING = ",.:;!?)»"


def line_bolds(values: list[float | None], fam: str, default: bool, texts: list[str]) -> list[bool]:
    """Bold or not for each word of a line (texts) from its boldness (None:
    not measured); see "a line's weights" in the glossary. default: the
    line's weight when nothing is measured."""
    line = BOLD_FROM[fam]
    sure = [v >= line for v in values if v is not None and abs(v - line) >= UNSURE]
    most = sum(sure) * 2 > len(sure) if sum(sure) * 2 != len(sure) else None
    decided = [None if v is None else (most if abs(v - line) < UNSURE and most is not None else v >= line)
               for v in values]
    closes = [t.rstrip()[-1:] in CLOSING for t in texts]
    out = []
    for n, d in enumerate(decided):
        if d is None:
            before = [m for m in range(n) if decided[m] is not None]
            after = [m for m in range(n + 1, len(decided)) if decided[m] is not None]
            starts = not any(c.isalnum() for c in texts[n]) or (n > 0 and closes[n - 1])
            if starts and after:
                d = decided[after[0]]
            elif closes[n] and before:
                d = decided[before[-1]]
            else:
                near = [(m - n, decided[m]) for m in after[:1]] + [(n - m, decided[m]) for m in before[-1:]]
                d = min(near, key=lambda pair: pair[0])[1] if near else default
        out.append(d)
    return out


def font_name(fam: str) -> str:
    return _FONT_FAMILIES[fam][0]
