"""MD -> TXT and MD -> DOCX (generic pandoc path)."""
import fixtures as fx
from conftest import is_docx, needs_pandoc

pytestmark = needs_pandoc


def test_md_to_txt(api, files):
    _, data = api.roundtrip(fx.markdown(files), "txt")
    text = data.decode("utf-8")
    assert "Markdown body text with bold word" in text
    assert "**" not in text


def test_md_to_docx(api, files):
    _, data = api.roundtrip(fx.markdown(files), "docx")
    assert is_docx(data)
