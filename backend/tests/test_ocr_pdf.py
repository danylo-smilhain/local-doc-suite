"""Scanned PDFs: OCR through Tesseract (ocrmypdf is optional)."""
import shutil

import pytest

import fixtures as fx
from conftest import is_docx, needs_tesseract

pytestmark = needs_tesseract


def test_scanned_pdf_to_txt_runs_ocr(api, files):
    # A full page, not a single word: see fixtures.SCANNED_PAGE_LINES.
    _, data = api.roundtrip(fx.scanned_page_pdf(files), "txt")
    text = data.decode("utf-8").upper()
    assert fx.OCR_WORD in text
    assert "SUPPLIER" in text


@pytest.mark.skipif(shutil.which("ocrmypdf") is not None,
                    reason="ocrmypdf installed: the ocrmypdf branch is taken instead")
def test_scanned_pdf_flow_mode_falls_back_to_tesseract(api, files):
    body, data = api.roundtrip(fx.scanned_pdf(files), "docx", pdf_docx_mode="flow")
    assert body["engine"] == "ocr-flow"
    assert body["ocr_mode"] == "tesseract"
    assert body["warning"]
    assert is_docx(data)


def test_scanned_pdf_layout_mode(api, files):
    body, data = api.roundtrip(fx.scanned_pdf(files), "docx-ocr")
    assert body["engine"] == "layout"
    assert body["layout"]["pages"] == 1
    assert is_docx(data)
