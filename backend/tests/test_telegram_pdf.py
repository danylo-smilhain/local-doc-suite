"""A Telegram export goes to PDF through its own Markdown, not raw LibreOffice."""
import fixtures as fx
from conftest import needs_libreoffice, needs_pandoc, pdf_text


@needs_pandoc
@needs_libreoffice
def test_telegram_pdf_uses_the_markdown_rendering(api, files):
    _, data = api.roundtrip(fx.telegram_html(files), "pdf")
    assert f"{fx.TELEGRAM_AUTHOR} · 10:00" in pdf_text(data)
