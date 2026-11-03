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


def test_ocr_line_is_shrunk_to_fit_its_place(pp):
    size = pp.fit_size("Спікер Марія Пальчук", 40, width_pt=300)
    assert size < 40
    import fitz
    assert fitz.Font("helv").text_length("Спікер Марія Пальчук", fontsize=size) <= 300.5
    assert pp.fit_size("PR", 40, width_pt=300) == 40          # already fits: unchanged

