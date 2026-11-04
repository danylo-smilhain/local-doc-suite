"""Slide and text-box geometry and the user warning for PDF -> PPTX, without files (app.pdf_pptx).

app.pdf_pptx pulls in app.config (through app.ocr), so it is imported only
after the harness has set up storage, as in test_routing_table.py."""
import pytest


@pytest.fixture(scope="module")
def pp(app):
    from app import pdf_pptx
    return pdf_pptx


def test_landscape_slide_keeps_the_page_proportions(pp):
    w, h = pp.slide_size(1440, 810)                      # Canva 16:9
    assert (w, h) == (pp.SLIDE_LONG_SIDE_EMU, 6858000)   # PowerPoint's own 13.333 x 7.5 in


def test_portrait_slide_has_the_long_side_vertical(pp):
    w, h = pp.slide_size(595, 842)                       # A4
    assert h == pp.SLIDE_LONG_SIDE_EMU and abs(w / h - 595 / 842) < 0.001


def test_page_with_the_slide_proportions_fills_the_slide(pp):
    assert pp.fit_box(1440, 810, *pp.slide_size(1440, 810)) == (0, 0, *pp.slide_size(1440, 810))


def test_other_page_size_is_centred_not_stretched(pp):
    sw, sh = pp.slide_size(1440, 810)
    left, top, w, h = pp.fit_box(595, 842, sw, sh)       # an A4 page in a 16:9 deck
    assert h == sh and top == 0
    assert abs(w / h - 595 / 842) < 0.001
    assert left == (sw - w) // 2 and left > 0


def test_line_box_puts_the_baseline_on_the_pdf_baseline(pp):
    runs = [{"size": 20, "x0": 100, "x1": 180, "origin_y": 300},
            {"size": 40, "x0": 180, "x1": 300, "origin_y": 300}]
    left, top, width, height = pp.line_box(runs)
    assert left == 100
    assert top == 300 - pp.BASELINE_EM * 40           # the largest run sets the line
    assert width == 200 + pp.WIDTH_SLACK_EM * 40
    assert top < 300 < top + height


def test_no_scans_or_recognised_scans_need_no_warning(pp):
    assert pp.scan_warning(0, ocr=False, tesseract=False) is None
    assert pp.scan_warning(3, ocr=True, tesseract=True) is None


def test_unreadable_pages_without_ocr_point_to_the_ocr_tool(pp):
    assert "PDF to PPTX (with OCR)" in pp.scan_warning(2, ocr=False, tesseract=True)


def test_ocr_without_tesseract_says_so(pp):
    assert "Tesseract is not installed" in pp.scan_warning(2, ocr=True, tesseract=False)


def run(text, x0=0):
    return {"text": text, "x0": x0, "x1": x0 + 50, "size": 10, "origin_y": 20}


@pytest.mark.parametrize("w,h,dpi", [(595, 842, 300), (1920, 1080, 132), (1440, 810, 175)])
def test_ocr_resolution_follows_the_page_size(pp, w, h, dpi):
    assert pp.ocr_dpi(w, h) == dpi                   # like an A4 page at 300 dpi, never above it


def test_a_title_slide_has_enough_words_for_ocr(pp):
    seg = lambda text: {"runs": [run(text)]}
    assert pp.ocr_found_text([seg("Спікер Марія Пальчук")])
    assert not pp.ocr_found_text([seg("Марія Пальчук")])
    assert not pp.ocr_found_text([seg("ii I1 . ~~ a")])  # photo noise


@pytest.mark.parametrize("fg,bg,expected", [((255, 255, 255), (242, 133, 46), "FFFFFF"),
                                            ((0, 0, 0), (255, 255, 255), "000000"),
                                            ((20, 90, 100), (245, 245, 245), "145A64")])
def test_ocr_text_colour_is_the_letters_not_the_background(pp, fg, bg, expected):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (120, 40), bg)
    ImageDraw.Draw(img).rectangle((20, 10, 100, 30), fill=fg)   # the "letters"
    assert pp.text_colour(img) == expected


def test_white_letters_on_a_button_on_a_white_card_are_white(pp):
    """The line's crop reaches past the button onto the white card: what
    differs most from its edge is the button. The letters are what the
    picture with the text painted out no longer has."""
    from PIL import Image, ImageDraw
    clean = Image.new("RGB", (120, 40), "white")
    ImageDraw.Draw(clean).rectangle((10, 5, 110, 35), fill=(253, 135, 53))
    img = clean.copy()
    ImageDraw.Draw(img).rectangle((25, 12, 95, 28), fill="white")
    assert pp.text_colour(img, clean) == "FFFFFF"
    assert pp.text_colour(img) != "FFFFFF"                       # by the edge alone: the button


def test_ocr_runs_use_a_sans_font(pp):
    from PIL import Image, ImageDraw
    seg = {"runs": [{"text": "Спікер", "font": "Times New Roman", "fam": "serif", "color": "000000",
                     "x0": 10, "x1": 90, "origin_y": 30, "size": 20}]}
    img = Image.new("RGB", (100, 40), (242, 133, 46))
    ImageDraw.Draw(img).rectangle((12, 15, 88, 29), fill=(255, 255, 255))
    run = pp.style_ocr_segments([seg], 1.0, img)[0]["runs"][0]
    assert run["fam"] == "sans" and run["font"] != "Times New Roman"
    assert run["color"] == "FFFFFF"
    long = {"runs": [dict(seg["runs"][0], text="Спікер Марія Пальчук", size=20)]}
    assert pp.style_ocr_segments([long], 1.0, img)[0]["runs"][0]["size"] < 20   # kept within x0..x1


def test_ocr_line_takes_the_size_that_fills_its_width(pp):
    """A word box is as tall as its tallest letters ("покази" has none), so
    the height misjudges the size; the width of the line does not."""
    import fitz
    helv = fitz.Font("helv")
    width = helv.text_length("- покази", fontsize=28)       # the line as wide as 28 pt text
    assert abs(pp.line_size("- покази", 17, width) - 28) < 0.01  # boxes said 17 pt: grown
    width = helv.text_length("Спікер Марія Пальчук", fontsize=28)
    assert abs(pp.line_size("Спікер Марія Пальчук", 40, width) - 28) < 0.01   # said 40: shrunk


def test_a_line_of_a_few_letters_keeps_its_height_size_within_its_width(pp):
    assert pp.line_size("1)", 30, width_pt=300) == 30            # too short to judge by width
    assert pp.line_size("1)", 30, width_pt=10) < 30


def test_line_size_never_goes_below_the_smallest_size_written(pp):
    from app.pdf_layout import LAYOUT_MIN_FONT_PT
    assert pp.line_size("a long line in a sliver of space", 20, width_pt=1) == LAYOUT_MIN_FONT_PT


@pytest.mark.parametrize("font,fam,bold", [("helv", "sans", False), ("hebo", "sans", True),
                                            ("tiro", "serif", False), ("tibo", "serif", True)])
@pytest.mark.parametrize("size", [14, 30, 80])     # 14 pt at 132 dpi: 26 px, above MIN_WEIGH_PX
@pytest.mark.parametrize("dpi", [132, 200])
def test_bold_is_measured_from_the_thickness_of_the_letters(pp, font, fam, bold, size, dpi):
    """Serif bold too: it is no thicker for its size than sans regular, but
    it is thicker than the same words in serif regular."""
    import fitz
    from PIL import Image
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((20, 120), "Maria Brand", fontsize=size, fontname=font)
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    width = fitz.Font(font).text_length("Maria Brand", fontsize=size)
    run = {"text": "Maria Brand", "size": size, "origin_y": 120, "x0": 20, "x1": 20 + width, "fam": fam,
           "font": "x", "bold": not bold, "italic": False, "color": "000000"}
    assert [r["bold"] for r in pp.weigh(run, img, dpi / 72)] == [bold]


def test_a_run_wider_in_arial_is_condensed_then_shrunk_to_its_width(pp):
    import fitz
    hebo = fitz.Font("hebo")
    text = "Стратегічне планування"
    wide = hebo.text_length(text, fontsize=25)
    size, spacing = pp.fit_run(text, 25, "sans", True, False, wide * 0.97)     # a little narrower
    assert size == 25 and -0.1 * 25 <= spacing < 0
    assert abs(wide + spacing * len(text) - wide * 0.97) < 0.01
    size, spacing = pp.fit_run(text, 25, "sans", True, False, wide * 0.7)      # much narrower
    assert spacing == -0.1 * size and size < 25
    assert abs(hebo.text_length(text, fontsize=size) + spacing * len(text) - wide * 0.7) < 0.01
    assert pp.fit_run(text, 25, "sans", True, False, wide * 1.2) == (25, 0)     # narrower in Arial: as is


@pytest.mark.parametrize("font,fam", [("tiro", "serif"), ("hebo", "sans")])
def test_a_word_too_short_to_measure_takes_its_neighbours_weight(pp, font, fam):
    """One letter says nothing about its weight ("і" in "витрати і
    фахівці" came out bold): it goes with the words around it."""
    import fitz
    from PIL import Image
    text = "Незручність і витрати"
    f = fitz.Font(font)
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    writer = fitz.TextWriter(page.rect)
    writer.append((20, 120), text, font=f, fontsize=30)       # insert_text draws no Cyrillic in Times
    writer.write_text(page)
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    words, x = [], 20
    for w in text.split():
        words.append((x, x + f.text_length(w, fontsize=30), w))
        x += f.text_length(w + " ", fontsize=30)
    run = {"text": text, "size": 30, "origin_y": 120, "x0": 20, "x1": words[-1][1], "fam": fam, "words": words,
           "font": "x", "bold": False, "italic": False, "color": "000000"}
    parts = pp.weigh(run, img, 150 / 72)
    assert [(p["text"], p["bold"]) for p in parts] == [(text, font == "hebo")]


def test_a_word_is_measured_in_its_own_box_not_in_a_misjudged_line(pp):
    """OCR's line size can be well off (a line of small letters); the band it
    gives cut the top of the letters, which then looked bold. OCR words carry
    their own top and bottom."""
    import fitz
    from PIL import Image
    text = "валют одній картці депозит"
    f = fitz.Font("tiro")
    doc = fitz.open()
    page = doc.new_page(width=700, height=200)
    writer = fitz.TextWriter(page.rect)
    writer.append((20, 120), text, font=f, fontsize=30)
    writer.write_text(page)
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    words, x = [], 20
    for w in text.split():
        words.append((x, x + f.text_length(w, fontsize=30), w, 120 - 30 * 0.5, 120 + 30 * 0.25))
        x += f.text_length(w + " ", fontsize=30)
    run = {"text": text, "size": 14, "origin_y": 118, "x0": 20, "x1": words[-1][1], "fam": "serif",
           "words": words, "font": "x", "bold": False, "italic": False, "color": "000000"}
    assert [p["bold"] for p in pp.weigh(run, img, 150 / 72)] == [False]


def test_a_short_word_goes_with_the_word_after_it(pp):
    """"з хештегом", "Чи відповідає": a short word belongs to what follows;
    at the end of a line to what came before."""
    from app.slide_fonts import line_bolds
    assert line_bolds([1.0, None, -0.3], "sans", False, ["хештегом", "з", "контентом"]) == [True, False, False]
    assert line_bolds([None, 1.0, None], "sans", False, ["з", "хештегом", "і"]) == [True, True, True]
    assert line_bolds([None, None], "sans", True, ["PR", "і"]) == [True, True]



def test_a_short_word_closing_a_phrase_goes_with_the_word_before_it(pp):
    """"в очах ЦА, brand equity": "ЦА," ends the regular phrase, so it goes
    with the words before it, not with "brand" after it."""
    import fitz
    from PIL import Image
    text = "бренду в очах ЦА, brand equity"
    f, fb = fitz.Font("helv"), fitz.Font("hebo")
    doc = fitz.open()
    page = doc.new_page(width=900, height=200)
    writer = fitz.TextWriter(page.rect)
    words, x = [], 20
    for w in text.split():
        font = fb if w in ("brand", "equity") else f
        writer.append((x, 120), w, font=font, fontsize=30)
        words.append((x, x + font.text_length(w, fontsize=30), w))
        x += font.text_length(w + " ", fontsize=30)
    writer.write_text(page)
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    run = {"text": text, "size": 30, "origin_y": 120, "x0": 20, "x1": words[-1][1], "fam": "sans", "words": words,
           "font": "x", "bold": False, "italic": False, "color": "000000"}
    assert [(p["text"].strip(), p["bold"]) for p in pp.weigh(run, img, 150 / 72)] == [
        ("бренду в очах ЦА,", False), ("brand equity", True)]


@pytest.mark.parametrize("font,bold", [("hebo", True), ("helv", False)])
def test_a_line_of_short_words_is_measured_all_the_same(pp, font, bold):
    """"PR" alone in its line: nothing longer to go by, so it is measured."""
    import fitz
    from PIL import Image
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 120), "PR", fontsize=60, fontname=font)
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    run = {"text": "PR", "size": 60, "origin_y": 120, "x0": 20, "x1": 20 + fitz.Font(font).text_length("PR", 60),
           "fam": "sans", "font": "x", "bold": not bold, "italic": False, "color": "000000"}
    assert [p["bold"] for p in pp.weigh(run, img, 150 / 72)] == [bold]


def test_a_two_letter_word_is_not_weighed_on_its_own(pp):
    """"Це люди, у яких": two letters weighed alone came out bold where they
    were not; they go with the words after them."""
    import fitz
    from PIL import Image
    text = "Це люди, у яких більше"
    f, fb = fitz.Font("helv"), fitz.Font("hebo")
    doc = fitz.open()
    page = doc.new_page(width=900, height=200)
    writer = fitz.TextWriter(page.rect)
    words, x = [], 20
    for w in text.split():
        font = fb if w == "Це" else f                     # as heavy as it was measured
        writer.append((x, 120), w, font=font, fontsize=30)
        words.append((x, x + font.text_length(w, fontsize=30), w))
        x += font.text_length(w + " ", fontsize=30)
    writer.write_text(page)
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    run = {"text": text, "size": 30, "origin_y": 120, "x0": 20, "x1": words[-1][1], "fam": "sans", "words": words,
           "font": "x", "bold": False, "italic": False, "color": "000000"}
    assert [p["bold"] for p in pp.weigh(run, img, 150 / 72)] == [False]


def test_a_serif_line_takes_its_size_from_times_widths(pp):
    import fitz
    text = "Розробка бізнес-моделі"
    width = 400.0
    assert abs(pp.line_size(text, 20, width, "serif") - width / fitz.Font("tiro").text_length(text, 1)) < 1e-6
    assert pp.line_size(text, 20, width, "serif") > pp.line_size(text, 20, width, "sans")


@pytest.mark.parametrize("text", ["CAC vs CPA", "(24/7)", "AVA VAT"])
def test_capitals_and_digits_do_not_make_a_line_italic(pp, text):
    """The diagonals of A, V, 7 and "/" lean like italic strokes: a line of
    capitals and digits is no evidence of a slant."""
    import fitz
    import numpy as np
    from PIL import Image
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((20, 120), text, fontsize=40, fontname="hebo")
    pix = page.get_pixmap(dpi=150, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    f = fitz.Font("hebo")
    words, x = [], 20
    for w in text.split():
        words.append((x, x + f.text_length(w, fontsize=40), w))
        x += f.text_length(w + " ", fontsize=40)
    run = {"text": text, "size": 40, "origin_y": 120, "x0": 20, "x1": words[-1][1], "words": words,
           "font": "x", "fam": "sans", "bold": True, "italic": False, "color": "000000"}
    k = 150 / 72
    picture = np.asarray(img)
    masks = [pp.letters(picture, run, x0, x1, k) for x0, x1, _ in words]
    assert not pp.italic(pp.slanted(masks, [w for *_, w in words]))
