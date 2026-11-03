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


def test_garbled_runs_are_dropped_and_the_line_is_cut_there(pp):
    run = lambda text, x0: {"text": text, "x0": x0, "x1": x0 + 50, "size": 10, "origin_y": 20}
    segs = [{"runs": [run("Good start", 0), run("\x11@5=4", 60), run("good end", 120)]},
            {"runs": [run("<5=546<5=B", 0)]}]
    out = pp.without_garbled(segs)
    assert [[r["text"] for r in s["runs"]] for s in out] == [["Good start"], ["good end"]]
    assert out[1]["runs"][0]["x0"] == 120              # keeps its own place


def run(text, x0=0):
    return {"text": text, "x0": x0, "x1": x0 + 50, "size": 10, "origin_y": 20}


@pytest.mark.parametrize("text", ["PR B0 ><C=V:0FVW", "PR-70EV4 O:", "\x11@5=4"])
def test_on_a_damaged_page_doubtful_runs_stay_in_the_picture(pp, text):
    assert pp.without_garbled([{"runs": [run(text)]}]) == []


@pytest.mark.parametrize("text", ["Clean heading here", "Digital PR", "презентації нових проєктів",
                                  "2024 рік", "Що таке PR-захід?"])
def test_on_a_damaged_page_plain_runs_become_text(pp, text):
    assert pp.without_garbled([{"runs": [run(text)]}]) != []


@pytest.mark.parametrize("w,h,dpi", [(595, 842, 300), (1920, 1080, 132), (1440, 810, 175)])
def test_ocr_resolution_follows_the_page_size(pp, w, h, dpi):
    assert pp.ocr_dpi(w, h) == dpi                   # like an A4 page at 300 dpi, never above it


def test_a_title_slide_has_enough_words_for_ocr(pp):
    seg = lambda text: {"runs": [run(text)]}
    assert pp.ocr_found_text([seg("Спікер Марія Пальчук")])
    assert not pp.ocr_found_text([seg("Марія Пальчук")])
    assert not pp.ocr_found_text([seg("ii I1 . ~~ a")])  # photo noise


def test_only_text_under_recognised_words_leaves_the_background(pp):
    import fitz
    title, body = fitz.Rect(100, 50, 600, 120), fitz.Rect(100, 300, 400, 330)
    words = [(110, 305, 200, 328)]                       # OCR found only the body line
    assert pp.rects_under_words([title, body], words) == [body]
