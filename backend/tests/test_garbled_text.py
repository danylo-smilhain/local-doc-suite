"""A text layer whose font lost its Unicode mapping (Canva exports with Type3
fonts: "Бренд-менеджмент" comes out as "\\x11@5=4-<5=546<5=B") must count as
broken, so OCR replaces it in PDF -> TXT / Word / PPTX with OCR, and PDF ->
PPTX without OCR leaves it in the picture instead of making garbage text."""
import pytest

import fixtures as fx
from conftest import needs_tesseract


@pytest.fixture(scope="module")
def ocr(app):
    from app import ocr
    return ocr


@pytest.mark.parametrize("text,type3", [
    ("\x11@5=4-<5=546<5=B", False),      # control characters: garbled in any font
    ("PR-70E>48?", True),                # "PR-захід?" from a Canva Type3 font
    ("=5 =0 G0AV", True),
])
def test_garbled_spans(ocr, text, type3):
    assert ocr.span_is_garbled(text, type3)


@pytest.mark.parametrize("text,type3", [
    ("А насправді?", True),              # punctuation at the end of a word is normal
    ("CHER17 2024", True),               # letters with digits are normal
    ("a<=b; c=d;", False),               # code in an ordinary font is not garbled
    ("Бренд-менеджмент", True),
    ("", True),
])
def test_normal_spans(ocr, text, type3):
    assert not ocr.span_is_garbled(text, type3)


def test_page_with_a_garbled_line_is_broken(ocr, files):
    import fitz
    with fitz.open(fx.garbled_text_pdf(files)) as doc:
        assert ocr.page_text_is_broken(doc[0])


def test_ordinary_text_page_is_not_broken(ocr, files):
    import fitz
    with fitz.open(fx.text_pdf(files)) as doc:
        assert not ocr.page_text_is_broken(doc[0])


def test_pptx_without_ocr_keeps_good_text_and_leaves_garbage_in_the_picture(api, files):
    from test_pdf_to_pptx import slide_text, slides_of
    body, data = api.roundtrip(fx.garbled_text_pdf(files), "pptx")
    text = slide_text(slides_of(data).slides[0])
    assert fx.CLEAN_LINE in text
    assert body.get("ocr_mode") is None              # nothing was recognised
    assert "<5=546" not in text and "\x11" not in text
    assert "with OCR" in body["warning"]


@needs_tesseract
def test_pptx_with_ocr_reads_the_page_instead_of_the_garbage(api, files):
    from test_pdf_to_pptx import slide_text, slides_of
    body, data = api.roundtrip(fx.garbled_text_pdf(files), "pptx-ocr")
    text = slide_text(slides_of(data).slides[0])
    assert body["ocr_mode"] == "tesseract"
    assert "SUPPLIER" in text.upper()
    assert "<5=546" not in text


@needs_tesseract
def test_pdf_to_txt_reads_the_page_instead_of_the_garbage(api, files):
    _, data = api.roundtrip(fx.garbled_text_pdf(files), "txt")
    text = data.decode("utf-8")
    assert "SUPPLIER" in text.upper()
    assert "<5=546" not in text
