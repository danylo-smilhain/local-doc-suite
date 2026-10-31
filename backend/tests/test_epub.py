"""EPUB -> MD (pandoc + footnote cleanup) and EPUB -> PDF (book layout + LibreOffice)."""
import fixtures as fx
from conftest import is_docx, is_pdf, needs_libreoffice, needs_pandoc, pdf_text


@needs_pandoc
def test_epub_to_md(api, files):
    _, data = api.roundtrip(fx.epub(files), "md")
    text = data.decode("utf-8")
    assert fx.EPUB_TEXT in text
    assert "<p>" not in text


@needs_pandoc
def test_epub_to_docx_generic_pandoc(api, files):
    _, data = api.roundtrip(fx.epub(files), "docx")
    assert is_docx(data)


@needs_libreoffice
def test_epub_to_pdf(api, files):
    body, data = api.roundtrip(fx.epub(files), "pdf")
    assert "warning" not in body          # own layout succeeded, no pandoc fallback
    assert is_pdf(data)
    assert "quick brown fox" in pdf_text(data)
