"""PDF details pinned while mutation-testing app/convert.py."""
import fixtures as fx
from conftest import docx_text, is_docx
from fixtures import zip_members


def test_markdown_escaping_only_for_md(api, files):
    pdf = fx.text_pdf(files, text="price*2 and a_b [x]")
    _, txt = api.roundtrip(pdf, "txt")
    _, md = api.roundtrip(pdf, "md")
    assert "price*2" in txt.decode("utf-8")
    assert "price\\*2" in md.decode("utf-8")


def test_clean_layout_has_no_ocr_warning(api, files):
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "docx")
    assert body["engine"] == "layout"
    assert body["warnings"] == []
    assert "ocr_mode" not in body


def test_layout_fallback_keeps_background_pictures(api, files, monkeypatch):
    import app.convert

    def broken_layout(*a, **kw):
        raise RuntimeError("layout engine down")

    monkeypatch.setattr(app.convert, "pdf_layout_to_docx", broken_layout)
    body, data = api.roundtrip(fx.background_pdf(files), "docx")
    assert body["engine"] == "pdf2docx"
    assert is_docx(data)
    assert any(m.startswith("word/media/") for m in zip_members(data))
    assert "<w:drawing" in docx_text(data)          # the picture is still placed in the body
    assert "background picture" in docx_text(data)
