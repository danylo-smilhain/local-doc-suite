"""All warnings of a conversion are returned, none overwritten (task 7)."""
import fixtures as fx


def test_layout_warnings_are_all_kept(api, files, monkeypatch):
    import app.convert

    def fake_layout(pdf_path, out_path, **kw):
        from docx import Document
        Document().save(out_path)
        return {"pages": 2, "ocr_pages": 1, "images": 0, "tables": 0,
                "graphics_notes": ["page 1: one picture"]}

    monkeypatch.setattr(app.convert, "pdf_layout_to_docx", fake_layout)
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "docx")
    assert len(body["warnings"]) == 2
    assert "page 1: one picture" in body["warnings"][0]
    assert "1 з 2" in body["warnings"][1]
    assert body["warning"] == "; ".join(body["warnings"])
    assert body["ocr_mode"] == "tesseract"
    assert body["engine"] == "layout"


def test_layout_failure_falls_back_with_a_warning(api, files, monkeypatch):
    import app.convert

    def broken_layout(*a, **kw):
        raise ValueError("boom")

    monkeypatch.setattr(app.convert, "pdf_layout_to_docx", broken_layout)
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "docx")
    assert body["engine"] == "pdf2docx"
    assert body["warnings"] and "ValueError: boom" in body["warnings"][0]
    assert "layout" not in body


def test_clean_conversion_has_empty_warnings(api, files):
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "txt")
    assert body["warnings"] == []
    assert "warning" not in body
