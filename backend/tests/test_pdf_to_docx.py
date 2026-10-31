"""PDF -> Word: page-layout engine by default, pdf2docx in flow mode."""
import fixtures as fx
from conftest import docx_text, is_docx


def test_pdf_to_docx_uses_layout_engine(api, files):
    body, data = api.roundtrip(fx.text_pdf(files), "docx")
    assert body["engine"] == "layout"
    assert body["layout"] == {"pages": 1, "ocr_pages": 0, "images": 0, "tables": 0}
    assert body["download_id"].endswith(".docx")
    assert is_docx(data)
    assert "apples" in docx_text(data)


def test_pdf_to_docx_ocr_target_also_uses_layout(api, files):
    body, data = api.roundtrip(fx.text_pdf(files), "docx-ocr")
    assert body["engine"] == "layout"
    assert body["download_id"].endswith(".docx")     # docx-ocr is saved as .docx
    assert is_docx(data)


def test_pdf_to_docx_flow_mode_uses_pdf2docx(api, files):
    body, data = api.roundtrip(fx.text_pdf(files), "docx", pdf_docx_mode="flow")
    assert body["engine"] == "pdf2docx"
    assert "warning" not in body
    assert is_docx(data)
    assert "apples" in docx_text(data)
