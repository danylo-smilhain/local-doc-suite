"""Word -> TXT / MD / EPUB / FB2 (pandoc) and Word -> PDF (LibreOffice)."""
import fixtures as fx
from conftest import is_epub, is_fb2, is_pdf, needs_libreoffice, needs_pandoc, pdf_text


@needs_pandoc
def test_docx_to_txt(api, files):
    _, data = api.roundtrip(fx.docx(files), "txt")
    assert fx.DOCX_TEXT in data.decode("utf-8")


@needs_pandoc
def test_docx_to_md(api, files):
    _, data = api.roundtrip(fx.docx(files), "md")
    text = data.decode("utf-8")
    assert "# Document heading" in text
    assert fx.DOCX_TEXT in text


@needs_pandoc
def test_docx_to_epub(api, files):
    _, data = api.roundtrip(fx.docx(files), "epub")
    assert is_epub(data)


@needs_pandoc
def test_docx_to_fb2(api, files):
    _, data = api.roundtrip(fx.docx(files), "fb2")
    assert is_fb2(data)
    assert fx.DOCX_TEXT.encode() in data


@needs_libreoffice
def test_docx_to_pdf(api, files):
    _, data = api.roundtrip(fx.docx(files), "pdf")
    assert is_pdf(data)
    assert fx.DOCX_TEXT in pdf_text(data)
