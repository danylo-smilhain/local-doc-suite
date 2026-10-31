"""engine_pandoc options: standalone metadata and footnotes only for books."""
import fixtures as fx
from conftest import needs_pandoc

pytestmark = needs_pandoc


def test_book_to_md_keeps_the_metadata_block(api, files):
    _, data = api.roundtrip(fx.epub(files), "md")
    assert data.decode("utf-8").startswith("---\nauthor: Test Author\n")


def test_word_to_md_has_no_metadata_block(api, files):
    _, data = api.roundtrip(fx.docx(files), "md")
    assert data.decode("utf-8").startswith("# Document heading")


def test_footnote_conversion_is_only_for_books(api, files):
    from docx import Document
    path = files / "notes.docx"
    d = Document()
    d.add_paragraph("Body text[1]")
    d.add_heading("Notes", 2)
    d.add_paragraph("1. The note")
    d.save(str(path))
    _, data = api.roundtrip(path, "md")
    text = data.decode("utf-8")
    assert "Body text\\[1\\]" in text and "[^" not in text



def test_book_to_txt_keeps_pandoc_line_wrapping(api, files):
    long_text = " ".join(["word"] * 60)
    _, data = api.roundtrip(fx.epub(files, text=long_text), "txt")
    lines = [l for l in data.decode("utf-8").splitlines() if "word" in l]
    assert len(lines) > 1 and max(len(l) for l in lines) <= 72
