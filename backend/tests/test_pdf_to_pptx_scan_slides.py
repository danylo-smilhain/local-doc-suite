"""PDF -> PPTX (with OCR) on slides that are only pictures and look nothing
like Canva: NotebookLM / Gemini exports (fixtures.notebook_slides_pdf), a
white page, serif or sans text, a table, icons. What the text-layer decks
get must hold here too: text within its cells and blocks, logos, icons,
lines and blocks as pictures of their own, the font's look and weight."""
import fixtures as fx
from conftest import needs_tesseract
from test_pdf_to_pptx import slides_of, text_boxes
from test_pdf_to_pptx_objects import placed

PAGE_W = 1376


def boxes_of(prs, slide):
    """(text, (x0, y0, x1, y1) in points) of every text box of a slide."""
    return [(b.text_frame.text, placed(prs, b, PAGE_W)) for b in text_boxes(slide)]


@needs_tesseract
def test_text_of_a_table_cell_stays_in_its_cell(api, files):
    """A cell's text ends 8 pt before the column's line and the next cell's
    starts 8 pt after it: nearer than a column gap, but a drawn line between
    two words ends the line of text there."""
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    boxes = boxes_of(prs, prs.slides[0])
    lines = fx.NOTE_COLUMNS
    for n, cell in enumerate(fx.NOTE_CELLS + fx.NOTE_HEADER):
        col = n % 3
        found = [b for t, b in boxes if cell in t]
        assert found, cell
        x0, _, x1, _ = found[0]
        assert lines[col] - 2 <= x0 and x1 <= lines[col + 1] + 6, (cell, found[0])


@needs_tesseract
def test_a_table_line_is_not_read_as_a_letter(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    assert not any("|" in t for t, _ in boxes_of(prs, prs.slides[0]))
