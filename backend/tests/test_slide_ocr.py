"""Reading the words of a slide picture (app.slide_ocr), without Tesseract:
merging two OCR passes, the second pass's input, and building lines.

app.slide_ocr pulls in app.config (through app.ocr), so it is imported only
after the harness has set up storage, as in test_pdf_pptx_layout.py."""
import pytest


@pytest.fixture(scope="module")
def so(app):
    from app import slide_ocr
    return slide_ocr


def test_where_two_passes_read_the_same_word_the_surer_reading_wins(so):
    W = so.Word
    plain = [W(10, 10, 90, 40, "САЗЕ", 90), W(100, 10, 160, 40, "для", 96)]
    other = [W(11, 9, 91, 41, "CASE", 96), W(102, 11, 158, 39, "для", 95)]
    assert sorted(w.text for w in so.best_words(plain, other)) == ["CASE", "для"]


def test_a_word_only_one_pass_saw_is_kept(so):
    W = so.Word
    plain = [W(10, 300, 90, 330, "Спікер", 96)]
    other = [W(10, 100, 900, 200, "БРЕНД-МЕНЕДЖМЕНТ", 91), W(12, 301, 88, 329, "Спікер", 95)]
    assert sorted(w.text for w in so.best_words(plain, other)) == ["БРЕНД-МЕНЕДЖМЕНТ", "Спікер"]


def test_the_second_pass_puts_the_last_language_first(so):
    assert so.other_order("ukr+rus+eng") == "eng+ukr+rus"
    assert so.other_order("eng") == "eng"


def test_coloured_letters_on_white_come_out_dark_for_the_second_pass(so):
    from PIL import Image
    img = Image.new("RGB", (2, 1), (255, 255, 255))
    img.putpixel((1, 0), (255, 133, 51))          # Canva orange: grey ~160 in luminance
    out = so.darkest_channel(img)
    assert out.mode == "L" and out.getpixel((0, 0)) == 255 and out.getpixel((1, 0)) == 51


def test_words_on_one_baseline_make_one_line_left_to_right(so):
    W = so.Word
    words = [W(140, 12, 200, 40, "як", 96), W(10, 0, 130, 45, "PR-захід", 70),
             W(10, 60, 200, 100, "інструмент", 96)]
    assert [[w.text for w in line] for line in so.lines_of(words)] == [["PR-захід", "як"], ["інструмент"]]


def test_two_columns_on_one_row_make_two_lines(so):
    W = so.Word
    words = [W(10, 0, 100, 30, "WHITE", 96), W(110, 0, 220, 30, "WEDDING", 96),
             W(700, 2, 800, 31, "Канади", 96), W(810, 2, 850, 31, "на", 96)]
    assert [[w.text for w in line] for line in so.lines_of(words)] == [["WHITE", "WEDDING"], ["Канади", "на"]]


def test_lines_come_top_to_bottom_whatever_their_indent(so):
    W = so.Word
    words = [W(300, 0, 400, 30, "first", 96), W(10, 60, 100, 90, "second", 96)]
    assert [[w.text for w in line] for line in so.lines_of(words)] == [["first"], ["second"]]


def test_unsure_and_empty_readings_are_dropped(so, monkeypatch):
    """On the Canva decks every misreading ("KC" for a checkmark, "R-3axonn?"
    for "PR-заходи?") came with confidence 84 or less; such a word stays in
    the picture, where it is drawn correctly."""
    data = {"text": ["CASE", "R-3axonn?", "~", "", "x"], "conf": ["96", "84", "30", "95", "-1"],
            "left": [1, 20, 2, 3, 4], "top": [1, 1, 1, 1, 1], "width": [9, 45, 9, 9, 9], "height": [5, 5, 5, 5, 5]}
    monkeypatch.setattr(so.pytesseract, "image_to_data", lambda *a, **k: data)
    assert so.read_words(None, "eng") == [so.Word(1, 1, 10, 6, "CASE", 96.0)]


def test_a_reading_too_narrow_for_its_letters_is_a_stroke_not_a_word(so, monkeypatch):
    """A frame edge or a rule comes out of Tesseract as "ся" or "|" in a box a
    pixel or two wide; a real narrow letter ("і") is wider than that."""
    data = {"text": ["ся", "і", "on"], "conf": ["90", "90", "90"],
            "left": [0, 50, 100], "top": [0, 0, 0], "width": [2, 9, 40], "height": [30, 30, 30]}
    monkeypatch.setattr(so.pytesseract, "image_to_data", lambda *a, **k: data)
    assert [w.text for w in so.read_words(None, "ukr")] == ["і", "on"]


def _picture(width=200, height=40, fill=(255, 255, 255)):
    import numpy as np
    a = np.zeros((height, width, 3), np.uint8)
    a[:] = fill
    return a


def test_a_line_drawn_between_two_words_ends_the_line(so):
    W = so.Word
    left, right = W(10, 5, 90, 35, "витрати", 96), W(110, 5, 190, 35, "Цифрові", 96)
    picture = _picture()
    assert [[w.text for w in ln] for ln in so.lines_of([left, right], picture)] == [["витрати", "Цифрові"]]
    picture[:, 99:101] = 0                          # a table's column line, 2 px
    assert [[w.text for w in ln] for ln in so.lines_of([left, right], picture)] == [["витрати"], ["Цифрові"]]


def test_words_on_a_coloured_block_stay_one_line(so):
    """The gap's own colour is the block's: only what stands out of it is a line."""
    W = so.Word
    picture = _picture(fill=(250, 220, 195))
    picture[:, 99:101] = (240, 210, 185)            # a faint shade is no line
    words = [W(10, 5, 90, 35, "Мета", 96), W(110, 5, 190, 35, "аналізу", 96)]
    assert [[w.text for w in ln] for ln in so.lines_of(words, picture)] == [["Мета", "аналізу"]]


def test_a_short_mark_in_the_gap_is_no_line(so):
    """A line runs the whole height the words share; a hyphen or a dot does not."""
    W = so.Word
    picture = _picture()
    picture[25:30, 99:101] = 0
    words = [W(10, 5, 90, 35, "до", 96), W(110, 5, 190, 35, "20%", 96)]
    assert len(so.lines_of(words, picture)) == 1


def test_a_line_read_as_a_bar_is_taken_off_the_word(so):
    W = so.Word
    assert so.without_rules(W(100, 0, 200, 30, "|відділень", 90)) == W(110, 0, 200, 30, "відділень", 90)
    cut = so.without_rules(W(100, 0, 200, 30, "банку||", 90))
    assert cut.text == "банку" and cut.x0 == 100 and abs(cut.x1 - (100 + 100 * 5 / 7)) < 1e-9
    assert so.without_rules(W(0, 0, 9, 30, "||", 90)) is None
    word = W(0, 0, 90, 30, "a|b", 90)
    assert so.without_rules(word) is word


def test_a_bar_alone_is_dropped_and_a_bar_beside_a_word_cut_off(so, monkeypatch):
    data = {"text": ["|", "|Цифрові"], "conf": ["92", "92"],
            "left": [0, 100], "top": [0, 0], "width": [12, 160], "height": [30, 30]}
    monkeypatch.setattr(so.pytesseract, "image_to_data", lambda *a, **k: data)
    assert [(w.text, w.x0) for w in so.read_words(None, "ukr")] == [("Цифрові", 120)]


def test_words_whose_boxes_touch_stay_one_line(so):
    """No gap at all between two words (Tesseract's boxes overlap): nothing
    can be drawn between them."""
    import warnings
    W = so.Word
    picture = _picture()
    picture[:, 95:100] = 0
    words = [W(10, 5, 100, 35, "PR-", 96), W(98, 5, 190, 35, "захід", 96)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(so.lines_of(words, picture)) == 1


def test_a_stroke_at_a_word_s_edge_is_no_line(so):
    """Word boxes are a few pixels off: the upright of the last letter just
    past its box is not a line between the words."""
    W = so.Word
    picture = _picture(width=400, height=80)
    picture[5:75, 101:104] = 0                      # "Д"'s upright, 1 px past the box
    words = [W(10, 5, 100, 75, "БРЕНД", 96), W(140, 5, 390, 75, "МЕНЕДЖМЕНТ", 96)]
    assert len(so.lines_of(words, picture)) == 1
    picture[5:75, 119:122] = 0                      # a line in the middle of the gap
    assert len(so.lines_of(words, picture)) == 2
