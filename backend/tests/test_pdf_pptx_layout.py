"""Slide geometry and notes text for PDF -> PPTX, without files (app.pdf_pptx).

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


def test_notes_text_drops_xml_invalid_characters(pp):
    assert pp.notes_text("  Title\x0cnext\x0bpage\x00 \n") == "Titlenextpage"
    assert pp.notes_text("Привіт\tсвіт\n") == "Привіт\tсвіт"


def test_no_scans_or_recognised_scans_need_no_warning(pp):
    assert pp.scan_warning(0, ocr=False, tesseract=False) is None
    assert pp.scan_warning(3, ocr=True, tesseract=True) is None


def test_scans_without_ocr_point_to_the_ocr_tool(pp):
    assert "PDF to PPTX (with OCR)" in pp.scan_warning(2, ocr=False, tesseract=True)


def test_ocr_without_tesseract_says_so(pp):
    assert "Tesseract is not installed" in pp.scan_warning(2, ocr=True, tesseract=False)
