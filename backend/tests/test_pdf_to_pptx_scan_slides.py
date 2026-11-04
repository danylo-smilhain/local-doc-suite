"""PDF -> PPTX (with OCR) on slides that are only pictures and look nothing
like Canva: NotebookLM / Gemini exports (fixtures.notebook_slides_pdf), a
white page, serif or sans text, a table, icons. What the text-layer decks
get must hold here too: text within its cells and blocks, logos, icons,
lines and blocks as pictures of their own, the font's look and weight."""
import fixtures as fx
from conftest import needs_tesseract
from test_pdf_to_pptx import PICTURE, slides_of, text_boxes
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


def pictures_of(prs, slide, page_w=PAGE_W):
    """(picture shape, box in points, locked) of every picture of a slide."""
    return [(s, placed(prs, s, page_w), b'noMove="1"' in s._element.xml.encode())
            for s in slide.shapes if s.shape_type == PICTURE]


def near(box, want, tol=6):
    return all(abs(a - b) <= tol for a, b in zip(box, want))


def image_of(shape):
    import io

    from PIL import Image
    return Image.open(io.BytesIO(shape.image.blob)).convert("RGBA")


@needs_tesseract
def test_logos_icons_lines_and_blocks_of_a_picture_slide_are_their_own_pictures(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    first, second = (pictures_of(prs, prs.slides[n]) for n in (0, 1))
    for want in (fx.NOTE_LOGO, fx.NOTE_ICON, fx.NOTE_RULE, fx.NOTE_BOX, fx.NOTE_TABLE):
        assert any(near(box, want) and not locked for _, box, locked in first), want
    assert any(near(box, fx.NOTE_ARROW) and not locked for _, box, locked in second)
    for pictures in (first, second):
        backs = [box for _, box, locked in pictures if locked]
        assert len(backs) == 1 and near(backs[0], (0, 0, PAGE_W, 768), tol=1)


@needs_tesseract
def test_moving_a_logo_off_a_picture_slide_shows_the_page(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    back = next(s for s, _, locked in pictures_of(prs, prs.slides[0]) if locked)
    img = image_of(back)
    s = img.width / PAGE_W
    for x0, y0, x1, y1 in (fx.NOTE_LOGO, fx.NOTE_ICON, fx.NOTE_BOX):
        assert min(img.getpixel((int((x0 + x1) / 2 * s), int((y0 + y1) / 2 * s)))[:3]) > 240


@needs_tesseract
def test_recognised_text_is_not_left_in_its_block(api, files):
    """The box keeps its colour under its text, which is a text box now; text
    left in the picture as well showed twice."""
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    box = next(s for s, b, locked in pictures_of(prs, prs.slides[0]) if near(b, fx.NOTE_BOX) and not locked)
    img = image_of(box).convert("RGB")
    dark = sum(1 for p in img.getdata() if max(p) < 150)
    assert dark == 0 and any(fx.NOTE_BOX_TEXT in t for t, _ in boxes_of(prs, prs.slides[0]))


@needs_tesseract
def test_a_frame_around_the_whole_slide_stays_in_its_background(api, files):
    """A border around the page, a texture or a fill over most of it is the
    slide's background: nothing that big is a picture of its own."""
    _, data = api.roundtrip(fx.canva_scan_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    pictures = pictures_of(prs, prs.slides[0], page_w=1440)
    big = [b for _, b, locked in pictures if not locked and (b[2] - b[0]) * (b[3] - b[1]) >= 0.5 * 1440 * 810]
    assert big == [] and sum(locked for *_, locked in pictures) == 1


@needs_tesseract
def test_no_scraps_of_letters_are_left_as_pictures(api, files, monkeypatch):
    """OCR's word boxes are a few pixels off the letters (the passes do not
    agree to the pixel); what sticks out of them must not become pictures
    of its own. Here every box is 3 px short on each side."""
    from app import pdf_pptx
    read = pdf_pptx.read_slide_words

    def short(img, lang):
        return [w._replace(x0=w.x0 + 3, y0=w.y0 + 3, x1=w.x1 - 3, y1=w.y1 - 3) for w in read(img, lang)]
    monkeypatch.setattr(pdf_pptx, "read_slide_words", short)
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    want = (fx.NOTE_LOGO, fx.NOTE_ICON, fx.NOTE_RULE, fx.NOTE_BOX, fx.NOTE_TABLE)
    loose = [box for _, box, locked in pictures_of(prs, prs.slides[0]) if not locked]
    assert all(any(near(box, w) for w in want) for box in loose), loose


@needs_tesseract
def test_a_word_too_few_to_be_text_stays_in_the_picture(api, files):
    """With fewer words than make a slide's text nothing becomes a text box,
    and nothing is painted out of the picture either."""
    import fitz
    import numpy as np
    from test_pdf_to_pptx import seen
    png = fx.text_image(files, "few.png")              # "INVOICE 2024"
    doc = fitz.open()
    doc.new_page(width=900, height=260).insert_image(fitz.Rect(0, 0, 900, 260), filename=str(png))
    doc.save(str(files / "few.pdf"))
    _, data = api.roundtrip(files / "few.pdf", "pptx-ocr")
    prs = slides_of(data)
    assert text_boxes(prs.slides[0]) == []
    dark = (np.asarray(seen(prs, prs.slides[0]).convert("L")) < 100).mean()
    assert dark > 0.002


def looks(prs, slide):
    """{text of a run: (font name, bold)} for every run of a slide's text."""
    return {r.text.strip(): (r.font.name, bool(r.font.bold))
            for b in text_boxes(slide) for p in b.text_frame.paragraphs for r in p.runs if r.text.strip()}


def look_of(runs, text):
    """The (font, bold) of the run holding text, or of all runs whose words make it up."""
    found = {v for k, v in runs.items() if k in text or text in k}
    assert len(found) == 1, (text, runs)
    return found.pop()


@needs_tesseract
def test_serif_text_gets_a_serif_font_and_keeps_its_weight(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    runs = looks(prs, prs.slides[0])
    assert look_of(runs, fx.NOTE_TITLE) == ("Times New Roman", True)
    for head in fx.NOTE_HEADER:
        assert look_of(runs, head) == ("Times New Roman", True), head
    for text in fx.NOTE_CELLS + [fx.NOTE_BOX_TEXT]:
        assert look_of(runs, text) == ("Times New Roman", False), text


@needs_tesseract
def test_sans_text_gets_a_sans_font_and_keeps_its_weight(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    runs = looks(prs, prs.slides[1])
    assert look_of(runs, fx.NOTE_SANS_TITLE) == ("Arial", True)
    assert look_of(runs, fx.NOTE_SANS_BODY) == ("Arial", False)


@needs_tesseract
def test_white_text_on_a_coloured_button_stays_white(api, files):
    """Around the button is the white page: the letters are what differs
    from the button under them, not what differs most from the page."""
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    runs = [r for b in text_boxes(prs.slides[1]) for p in b.text_frame.paragraphs for r in p.runs
            if fx.NOTE_BUTTON_TEXT in r.text]
    assert runs and all(min(r.font.color.rgb) > 230 for r in runs), [str(r.font.color.rgb) for r in runs]


@needs_tesseract
def test_italic_text_stays_italic(api, files):
    _, data = api.roundtrip(fx.notebook_slides_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    runs = [r for b in text_boxes(prs.slides[0]) for p in b.text_frame.paragraphs for r in p.runs if r.text.strip()]
    slanted = {r.text.strip(): bool(r.font.italic) for r in runs}
    assert any(t in fx.NOTE_ITALIC and v for t, v in slanted.items()), slanted
    assert not any(v for t, v in slanted.items() if t not in fx.NOTE_ITALIC), slanted
    # its strokes are measured stood upright: a regular serif, not a bold sans
    looks_of = {(r.font.name, bool(r.font.bold)) for r in runs if r.text.strip() in fx.NOTE_ITALIC}
    assert looks_of == {("Times New Roman", False)}, looks_of
