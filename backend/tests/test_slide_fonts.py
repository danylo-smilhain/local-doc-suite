"""Serif or sans, bold or regular, read from the strokes of drawn words
(app.slide_fonts). The words are drawn in DejaVu and Liberation fonts and
compared with Helvetica and Times: no font has to match the one measured."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

DV = "/usr/share/fonts/truetype/dejavu/"
LIB = "/usr/share/fonts/truetype/liberation/"
FONTS = {
    ("sans", False): [DV + "DejaVuSans.ttf", LIB + "LiberationSans-Regular.ttf"],
    ("sans", True): [DV + "DejaVuSans-Bold.ttf", LIB + "LiberationSans-Bold.ttf"],
    ("serif", False): [DV + "DejaVuSerif.ttf", LIB + "LiberationSerif-Regular.ttf"],
    ("serif", True): [DV + "DejaVuSerif-Bold.ttf", LIB + "LiberationSerif-Bold.ttf"],
}
LINES = ["Висока вартість банківських послуг", "Цифрова молодь та фахівці", "Strategic planning and brand growth",
         "Готівка сторонні сервіси переказів", "Мандрівники та власники валюти"]
LINE = LINES[0]


def bolds(sf, measured, fam="sans"):
    """Bold or not for each of a page's measured words."""
    return [sf.bold_of(m, fam) for m in measured]


@pytest.fixture(scope="module")
def sf(app):
    from app import slide_fonts
    return slide_fonts


def word(sf, text, path, px):
    """The ink of one word drawn at px pixels."""
    font = ImageFont.truetype(path, px)
    img = Image.new("RGB", (int(px * (len(text) + 1)), px * 2), "white")
    ImageDraw.Draw(img).text((px // 2, px // 3), text, font=font, fill="black")
    return sf.ink(np.asarray(img))


@pytest.mark.parametrize("fam,bold", list(FONTS))
@pytest.mark.parametrize("px", [45, 55, 66, 80, 100])
def test_the_family_of_a_line_is_seen_in_its_strokes(sf, fam, bold, px):
    for path in FONTS[fam, bold]:
        for line in LINES:
            texts = [w for w in line.split() if len(w) >= 3]
            masks = [word(sf, w, path, px) for w in texts]
            assert sf.family(masks, px, texts) == fam, (path, line)


def test_small_letters_say_nothing_and_stay_sans(sf):
    masks = [word(sf, w, FONTS["serif", False][0], 30) for w in LINE.split()]
    assert sf.family(masks, 30) == "sans" and sf.family([], 66) == "sans"


@pytest.mark.parametrize("fam,bold", list(FONTS))
def test_bold_is_told_from_regular_in_either_family(sf, fam, bold):
    for path in FONTS[fam, bold]:
        for text in ("послуг", "Проблема", "Growth"):
            assert sf.is_bold(word(sf, text, path, 66), text, fam) == bold, (path, text)


def test_a_word_with_nothing_drawn_is_not_bold(sf):
    assert not sf.is_bold(np.zeros((0, 0), bool), "слово", "sans")
    assert not sf.is_bold(np.ones((20, 40), bool), "  ", "sans")


def test_the_ink_of_a_word_is_its_letters_trimmed(sf):
    a = np.full((30, 50, 3), 250, np.uint8)
    a[10:20, 5:25] = (170, 11, 10)
    a[12, 30] = (240, 240, 240)                    # a faint speck: not ink
    mask = sf.ink(a)
    assert mask.shape == (10, 20) and mask.all()
    assert sf.ink(np.full((5, 5, 3), 9, np.uint8)).size == 0


def test_runs_and_their_commonest_length(sf):
    mask = np.array([[1, 1, 0, 1, 1, 1, 0, 1, 1]], bool)
    assert list(sf.runs(mask)) == [2, 3, 2]
    assert sf.commonest(np.array([], int)) == 0.0
    assert sf.commonest(np.array([2, 2, 2, 3])) == pytest.approx(2.25)


def heavy(sf, text, px, bold):
    """A serif whose regular is heavier than Times' (as Gemini's is): DejaVu
    Serif with its strokes a pixel thicker; its bold, DejaVu Serif Bold."""
    font = ImageFont.truetype(FONTS["serif", True][0] if bold else FONTS["serif", False][0], px)
    img = Image.new("RGB", (int(px * (len(text) + 1)), px * 2), "white")
    ImageDraw.Draw(img).text((px // 2, px // 3), text, font=font, fill="black", stroke_width=0 if bold else 1,
                             stroke_fill="black")
    return sf.ink(np.asarray(img))


WORDS = ["Вартість", "послуг", "відкриття", "обслуговування", "перекази", "застосунку", "картка", "депозит"]


def test_a_regular_heavier_than_times_is_not_bold(sf):
    """A heavy regular (as Gemini's serif) sits up to two thirds of the way
    from Times regular to Times bold; its bold beyond that."""
    bold = [n % 3 == 0 for n in range(len(WORDS))]
    measured = [sf.relative_weight(heavy(sf, w, 66, b), w, "serif") for w, b in zip(WORDS, bold)]
    assert bolds(sf, measured, "serif") == bold


def test_a_page_of_one_weight_is_judged_against_the_drawn_words(sf):
    for path, bold in ((FONTS["sans", False][1], False), (FONTS["sans", True][1], True)):
        measured = [sf.relative_weight(word(sf, w, path, 66), w, "sans") for w in WORDS]
        assert bolds(sf, measured) == [bold] * len(WORDS), path


def test_words_not_measured_stay_unknown(sf):
    assert sf.relative_weight(np.zeros((0, 0), bool), "слово", "sans") is None
    assert bolds(sf, [None, None]) == [None, None]


def test_each_word_is_weighed_against_its_own_text_drawn(sf):
    """Bold weighs 1.2 to 2.3 times regular depending on the letters ("типу"
    or "Типи"): a word is placed between its own text drawn regular and
    drawn bold. Measured on a Canva slide: a title and a paragraph."""
    title = [(1.6, 1.6), (2.18, 2.28), (1.63, 1.64)]
    body = [(0.85, 1.62), (0.83, 1.59), (0.75, 1.52), (0.94, 1.81), (1.03, 1.18)]
    assert bolds(sf, title + body) == [True] * 3 + [False] * 5
    assert bolds(sf, title[1:]) == [True, True]                     # a page of one weight


def test_a_measure_out_of_bounds_does_not_vote(sf):
    """An underline under "типу" left its body 7 px high: 3.84 times regular.
    "KPI" drawn bold in Helvetica is no heavier than regular: nothing to
    tell. Neither may move the page's split."""
    title, body = [(1.6, 1.6), (1.6, 1.62)], [(0.85, 1.62), (0.83, 1.59), (0.8, 1.6)]
    assert bolds(sf, title + body + [(3.84, 1.18), (0.89, 0.94)]) == [True] * 2 + [False] * 3 + [None, None]


def test_two_words_are_too_few_to_split_a_page(sf):
    """"Ролі інфлюенсерів", both bold, 1.27 and 0.97 bold: no second weight."""
    assert bolds(sf, [(2.06, 1.77), (1.6, 1.63)]) == [True, True]
    # a logo's "space" (0.56), a title and a button (0.88-1.32)
    assert bolds(sf, [(1.33, 1.67), (1.78, 1.62), (1.83, 1.58), (1.46, 1.54)]) == [True] * 4


@pytest.mark.parametrize("bold", [False, True])
def test_bold_capitals_are_told_by_their_whole_height(sf, bold):
    """Capitals have no x-height: the rows with most ink are their bars
    (Е, Н, Ф), not a body to weigh the stems against."""
    path = FONTS["sans", bold][0]
    for text in ("КОНФЕРЕНЦІЇ", "ВОРКШОПИ", "KPI MARKETING"):
        masks = [word(sf, w, path, 66) for w in text.split()]
        assert all(sf.is_bold(m, w, "sans") == bold for m, w in zip(masks, text.split())), text


def test_capitals_and_digits_have_no_x_height(sf):
    assert sf.no_x_height("КОНФЕРЕНЦІЇ") and sf.no_x_height("5) КУЛЬТУРНІ") and not sf.no_x_height("Канали")
    assert sf.no_x_height("2024") and sf.no_x_height("3") and not sf.no_x_height("–")


def test_words_as_heavy_as_bold_stay_bold_next_to_a_heavier_title(sf):
    """A Canva slide: a title in heavy capitals (1.25 bold) over buttons in a
    semibold (0.86-1.03): the buttons are bold, not the page's regular."""
    title = [(1.79, 1.6)]
    buttons = [(1.57, 1.6), (1.54, 1.55), (1.56, 1.57), (1.52, 1.58), (1.58, 1.6), (1.56, 1.67), (1.53, 1.52)]
    assert bolds(sf, title + buttons) == [True] * 8


def test_marks_above_capitals_do_not_change_their_weight(sf):
    """The dots of "Ї" sit higher in some fonts than in Helvetica: they are
    not part of the height the stems are weighed against."""
    mask = word(sf, "КОНФЕРЕНЦІЇ", FONTS["sans", True][0], 66)
    h, w = mask.shape
    dotted = np.zeros((h + 30, w), bool)
    dotted[30:] = mask
    dotted[0:6, w - 30:w - 24] = dotted[0:6, w - 14:w - 8] = True        # two dots far above
    assert abs(sf.weight(dotted, True) / sf.weight(mask, True) - 1) < 0.05


def test_strokes_measured_wrong_have_no_vote(sf):
    """A word whose bars come out thicker than its stems (a mis-measure:
    0.28 for Gemini's "функціональні") does not drag its line to sans."""
    upright = np.zeros((100, 12), bool)
    upright[:, :] = True                                         # contrast 0.12
    serif = [word(sf, w, FONTS["serif", False][0], 66) for w in ("вартість", "послуг")]
    assert sf.contrast(upright) < sf.MIN_CONTRAST
    assert sf.family([upright] * 3 + serif, 66) == "serif"


def test_a_semibold_sans_is_bold_a_heavy_serif_regular_is_not(sf):
    """Times regular is lighter than most serifs' regular (Gemini's sits at
    0.64 of the way to Times bold); Helvetica regular is a typical sans. So a
    sans word a third of the way to bold is bold (Canva's semibold: 0.44 to
    0.72, its regular -0.15 or less), a serif word two thirds of the way."""
    semibold = (1.21, 1.55)          # "ПРЕСТУР", boldness 0.44, on Lesson 6
    regular = (0.91, 1.67)           # "через", -0.18, on the same slide
    assert sf.bold_of(semibold, "sans") and not sf.bold_of(semibold, "serif")
    assert not sf.bold_of(regular, "sans")


def test_gemini_s_serif_regular_and_bold_each_word_against_its_own_text(sf):
    """Measured on a Gemini slide, each word with its own text drawn in
    Times: regular up to 0.64, bold from 0.70."""
    regular = [(1.31, 1.52), (1.29, 1.51), (1.28, 1.52), (1.27, 1.52)]   # Віртуальна, рік, (пріоритет, планами
    bold = [(1.41, 1.63), (1.42, 1.61), (1.54, 1.74), (1.6, 1.62)]       # засади, Lean, Canvas, Теоретичні
    assert bolds(sf, regular + bold, "serif") == [False] * 4 + [True] * 4


def test_a_bold_barely_heavier_than_its_regular_tells_nothing(sf):
    """Drawn bold only 8% heavier than drawn regular, a word's place between
    them is noise (here it would be 0.63 of the way)."""
    assert sf.boldness((1.05, 1.08)) is None and sf.boldness((1.05, 1.2)) is not None


@pytest.mark.parametrize("bold", [False, True])
def test_a_digit_is_weighed_by_its_whole_height(sf, bold):
    """A big "3" alone on its line: its fullest rows are its bars, no body;
    measured against them it came out five times regular and was dropped."""
    path = FONTS["sans", bold][1]
    for text in ("7", "77", "2024"):
        assert sf.is_bold(word(sf, text, path, 120), text, "sans") == bold, text


def test_a_short_word_goes_with_its_nearest_measured_neighbour(sf):
    """"@Top Blogers UA – канал": "UA" is next to "Blogers", "канал" is two
    words away; "–" is nearer "канал"."""
    line = ["@Top", "Blogers", "UA", "–", "канал"]
    assert sf.line_bolds([1.19, 0.83, None, None, -0.54], "sans", False, line) == [True, True, True, False, False]
    # on a tie, the word after it ("з хештегом"), unless it closes a phrase
    assert sf.line_bolds([-0.5, None, 1.0], "sans", False, ["контент", "з", "хештегом"]) == [False, True, True]
    assert sf.line_bolds([-0.5, None, 1.0], "sans", False, ["очах", "ЦА,", "brand"]) == [False, False, True]


def test_a_dash_or_a_word_after_a_comma_starts_what_follows(sf):
    """"CPA – це вартість": the dash goes with "це", not "CPA"; "Даруйте
    емоції, а не покупку": "а" after the comma goes with "не покупку"."""
    assert sf.line_bolds([1.0, None, None, -0.4], "sans", False, ["CPA", "–", "це", "вартість"]) == [
        True, False, False, False]
    assert sf.line_bolds([1.0, 1.0, None, None, -0.3], "sans", False, ["Даруйте", "емоції,", "а", "не", "покупку."]) == [
        True, True, False, False, False]


def test_a_word_near_the_threshold_goes_with_its_line(sf):
    """Measured on a Gemini slide (serif, bold from 0.67): "Схема" (0.59) in
    a bold title, "Віртуальна" (0.64) in a regular line."""
    words = ["Схема", "бізнес-моделі", "Lean", "Canvas:"]
    assert sf.line_bolds([0.59, 0.9, 0.85, 0.95], "serif", False, words) == [True] * 4
    assert sf.line_bolds([0.64, 0.3, 0.2, 0.1], "serif", False, words) == [False] * 4
    assert sf.line_bolds([0.64], "serif", False, ["Віртуальна"]) == [False]     # alone: the threshold decides


ITALICS = {False: [DV + "DejaVuSans.ttf", DV + "DejaVuSerif.ttf", LIB + "LiberationSerif-Regular.ttf",
                   LIB + "LiberationSans-Bold.ttf"],
           True: [DV + "DejaVuSans-Oblique.ttf", DV + "DejaVuSerif-Italic.ttf", LIB + "LiberationSerif-Italic.ttf",
                  LIB + "LiberationSans-Italic.ttf", LIB + "LiberationSerif-BoldItalic.ttf"]}


@pytest.mark.parametrize("italic", [False, True])
@pytest.mark.parametrize("px", [30, 45, 66])
def test_italic_is_seen_in_the_slant_of_the_strokes(sf, italic, px):
    """Upright fonts measure -0.03 to 0.02, italic and oblique 0.16 to 0.20."""
    for path in ITALICS[italic]:
        masks = [word(sf, w, path, px) for w in ("Саме", "цій", "групі", "перевіряються", "гіпотези")]
        assert sf.italic(masks) == italic, path


def test_no_words_are_not_italic(sf):
    assert not sf.italic([])


def squeezed(sf, text, path, px, k):
    """A word drawn narrower, as a condensed font is: its uprights thinner,
    its bars as thick."""
    m = word(sf, text, path, px)
    img = Image.fromarray(m.astype(np.uint8) * 255).resize((max(1, round(m.shape[1] * k)), m.shape[0]), Image.LANCZOS)
    return np.asarray(img) > 127


@pytest.mark.parametrize("fam", ["serif", "sans"])
@pytest.mark.parametrize("k", [0.7, 0.8])
def test_a_condensed_font_keeps_its_family(sf, fam, k):
    """A narrow serif (Lean Canvas, slide 10: 0.78 of Helvetica's width)
    has thinner uprights, so its stroke contrast looks like a sans's (1.25-1.4);
    over its width it is a serif's again. A narrow sans stays sans."""
    path = FONTS[fam, False][0]
    for line in LINES:
        masks = [squeezed(sf, w, path, 66, k) for w in line.split() if len(w) >= 3]
        texts = [w for w in line.split() if len(w) >= 3]
        assert sf.family(masks, 66, texts) == fam, (line, k)


def test_an_italic_line_takes_the_family_of_its_page(sf):
    """Italic serif has no feet and leaner uprights: Gemini's measured as a
    sans (contrast 1.3-1.55, feet 1.2-1.5). A deck sets its italic in the
    family of its upright text."""
    fams = ["serif", "serif", "sans", "serif", "sans"]
    slanted = [False, False, False, True, True]
    assert sf.page_families(fams, slanted) == ["serif", "serif", "sans", "serif", "serif"]
    assert sf.page_families(["sans", "serif"], [True, True]) == ["sans", "serif"]       # nothing upright
    assert sf.page_families(["serif", "sans", "serif"], [False, False, True]) == ["serif", "sans", "serif"]  # a tie


def test_a_word_leaning_a_little_is_not_italic(sf):
    """An upright bold heading measured 0.10 on a Gemini slide (a short
    line); a photographed page leans a little too. Italic leans 0.14 and more."""
    for lean in (0.06, 0.09):
        masks = []
        for w in ("Загальні", "сегменти", "клієнта"):
            m = word(sf, w, FONTS["sans", True][1], 66)
            img = Image.fromarray(m.astype(np.uint8) * 255)
            img = img.transform((img.width + 20, img.height), Image.AFFINE, (1, lean, -lean * img.height / 2, 0, 1, 0),
                                resample=Image.BILINEAR)
            masks.append(np.asarray(img) > 127)
        assert not sf.italic(masks), lean
