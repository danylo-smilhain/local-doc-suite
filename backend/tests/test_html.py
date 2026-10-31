"""HTML -> MD / TXT / DOCX (pandoc), HTML -> PDF (LibreOffice), Telegram exports."""
import fixtures as fx
from conftest import is_docx, is_pdf, needs_libreoffice, needs_pandoc, pdf_text


@needs_pandoc
def test_html_to_md_has_no_raw_html(api, files):
    _, data = api.roundtrip(fx.html(files), "md")
    text = data.decode("utf-8")
    assert fx.HTML_TEXT in text
    assert "<div" not in text


@needs_pandoc
def test_html_to_txt(api, files):
    _, data = api.roundtrip(fx.html(files), "txt")
    assert fx.HTML_TEXT in data.decode("utf-8")


@needs_pandoc
def test_html_to_docx(api, files):
    _, data = api.roundtrip(fx.html(files), "docx")
    assert is_docx(data)


@needs_libreoffice
def test_html_to_pdf(api, files):
    _, data = api.roundtrip(fx.html(files), "pdf")
    assert is_pdf(data)
    assert fx.HTML_TEXT in pdf_text(data)


def test_telegram_export_to_md(api, files):
    _, data = api.roundtrip(fx.telegram_html(files), "md")
    text = data.decode("utf-8")
    assert text.startswith(f"# {fx.TELEGRAM_CHAT}")
    assert "## 12 March 2024" in text
    assert f"**{fx.TELEGRAM_AUTHOR}** · 10:00" in text
    assert fx.TELEGRAM_MESSAGE in text


@needs_pandoc
@needs_libreoffice
def test_telegram_export_to_pdf(api, files):
    _, data = api.roundtrip(fx.telegram_html(files), "pdf")
    assert is_pdf(data)
    assert fx.TELEGRAM_MESSAGE in pdf_text(data)
