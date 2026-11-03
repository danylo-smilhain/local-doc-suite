"""PDF -> PPTX: one slide per page, the page as a picture, its text in the notes.

A designed PDF (Canva, Keynote, PowerPoint export) keeps its exact look this
way; the page text goes to the speaker notes so it can still be copied and
searched, recognised by OCR when the page is a scan."""
import io

import fixtures as fx
from conftest import is_pptx, needs_tesseract


def slides_of(data: bytes):
    from pptx import Presentation
    return Presentation(io.BytesIO(data))


def canva_like_pdf(directory, pages: int = 3):
    """16:9 pages (1440 x 810 pt) like a Canva presentation export."""
    import fitz
    path = directory / "deck.pdf"
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=1440, height=810)
        page.draw_rect(page.rect, color=None, fill=(0.95, 0.6, 0.2))
        page.insert_text((100, 200), f"Lesson slide {i + 1}", fontsize=60)
    doc.save(str(path))
    doc.close()
    return path


def test_every_page_becomes_a_full_slide_picture(api, files):
    body, data = api.roundtrip(canva_like_pdf(files), "pptx")
    assert is_pptx(data)
    prs = slides_of(data)
    assert len(prs.slides) == 3
    assert abs(prs.slide_width / prs.slide_height - 1440 / 810) < 0.01
    for slide in prs.slides:
        pictures = [s for s in slide.shapes if s.shape_type == 13]  # MSO_SHAPE_TYPE.PICTURE
        assert len(pictures) == 1
        assert (pictures[0].width, pictures[0].height) == (prs.slide_width, prs.slide_height)


def test_page_text_goes_to_the_speaker_notes(api, files):
    _, data = api.roundtrip(canva_like_pdf(files), "pptx")
    notes = [s.notes_slide.notes_text_frame.text for s in slides_of(data).slides]
    assert [("Lesson slide %d" % (i + 1)) in n for i, n in enumerate(notes)] == [True, True, True]


def test_portrait_pages_make_portrait_slides(api, files):
    _, data = api.roundtrip(fx.text_pdf(files, pages=2), "pptx")
    prs = slides_of(data)
    assert len(prs.slides) == 2
    assert abs(prs.slide_width / prs.slide_height - 595 / 842) < 0.01
    assert fx.PDF_TEXT in prs.slides[0].notes_slide.notes_text_frame.text


@needs_tesseract
def test_scanned_page_text_is_recognised_into_the_notes(api, files):
    _, data = api.roundtrip(fx.scanned_page_pdf(files), "pptx")
    notes = slides_of(data).slides[0].notes_slide.notes_text_frame.text.upper()
    assert fx.OCR_WORD in notes
