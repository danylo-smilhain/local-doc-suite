"""FB2 -> MD (with author/title header) and FB2 -> PDF (pandoc DOCX + LibreOffice)."""
import fixtures as fx
from conftest import is_pdf, needs_libreoffice, needs_pandoc, pdf_text


@needs_pandoc
def test_fb2_to_md_adds_author_and_title_header(api, files):
    _, data = api.roundtrip(fx.fb2(files), "md")
    text = data.decode("utf-8")
    assert text.startswith(f"# {fx.FB2_AUTHOR_FIRST} {fx.FB2_AUTHOR_LAST}\n\n## {fx.FB2_TITLE}\n\n---\n\n")
    assert fx.FB2_TEXT in text


@needs_pandoc
@needs_libreoffice
def test_fb2_to_pdf(api, files):
    _, data = api.roundtrip(fx.fb2(files), "pdf")
    assert is_pdf(data)
    assert "green forest" in pdf_text(data)
