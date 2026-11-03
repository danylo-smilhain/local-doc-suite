"""PDF -> PPTX, page for page, the way PDF -> Word does it: each slide has the
page's background (pictures, colour, graphics) as a picture WITHOUT the text,
and the text on top as editable PowerPoint text boxes in the same places.
"pptx" uses the PDF's own text layer; "pptx-ocr" also recognises scanned pages."""
import io

import fixtures as fx
from conftest import is_pptx, needs_tesseract

PICTURE = 13  # MSO_SHAPE_TYPE.PICTURE
ORANGE = (0.95, 0.6, 0.2)


def slides_of(data: bytes):
    from pptx import Presentation
    return Presentation(io.BytesIO(data))


def text_boxes(slide):
    return [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]


def slide_text(slide) -> str:
    return "\n".join(s.text_frame.text for s in text_boxes(slide))


def pictures(slide):
    return [s for s in slide.shapes if s.shape_type == PICTURE]


def canva_like_pdf(directory, pages: int = 3):
    """16:9 pages (1440 x 810 pt) like a Canva presentation export: a coloured
    background, a big white bold title, a blue line of body text."""
    import fitz
    path = directory / "deck.pdf"
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=1440, height=810)
        page.draw_rect(page.rect, color=None, fill=ORANGE)
        page.insert_text((100, 200), f"Lesson slide {i + 1}", fontsize=60, fontname="hebo", color=(1, 1, 1))
        page.insert_text((100, 400), "Body text in blue", fontsize=30, color=(0, 0, 1))
    doc.save(str(path))
    doc.close()
    return path


def test_every_page_becomes_a_slide_with_the_page_proportions(api, files):
    _, data = api.roundtrip(canva_like_pdf(files), "pptx")
    assert is_pptx(data)
    prs = slides_of(data)
    assert len(prs.slides) == 3
    assert abs(prs.slide_width / prs.slide_height - 1440 / 810) < 0.01


def test_text_is_editable_on_the_slide_with_its_size_colour_and_weight(api, files):
    _, data = api.roundtrip(canva_like_pdf(files), "pptx")
    prs = slides_of(data)
    pt = prs.slide_width / 1440                       # EMU per PDF point
    runs = {r.text.strip(): r for s in text_boxes(prs.slides[0])
            for p in s.text_frame.paragraphs for r in p.runs if r.text.strip()}
    title, body = runs["Lesson slide 1"], runs["Body text in blue"]
    assert abs(title.font.size / pt - 60) < 1.5 and title.font.bold
    assert str(title.font.color.rgb) == "FFFFFF"
    assert abs(body.font.size / pt - 30) < 1 and not body.font.bold
    assert str(body.font.color.rgb) == "0000FF"
    assert [slide_text(s).count("Lesson slide") for s in prs.slides] == [1, 1, 1]


def test_text_box_sits_where_the_text_was(api, files):
    _, data = api.roundtrip(canva_like_pdf(files), "pptx")
    prs = slides_of(data)
    pt = prs.slide_width / 1440
    box = next(s for s in text_boxes(prs.slides[0]) if "Lesson slide 1" in s.text_frame.text)
    assert abs(box.left / pt - 100) < 3
    assert box.top / pt < 200 < (box.top + box.height) / pt   # the baseline (y = 200) is inside


def test_background_is_the_page_without_its_text_and_stays_put(api, files):
    from PIL import Image
    _, data = api.roundtrip(canva_like_pdf(files), "pptx")
    prs = slides_of(data)
    bg = pictures(prs.slides[0])
    assert len(bg) == 1 and (bg[0].width, bg[0].height) == (prs.slide_width, prs.slide_height)
    img = Image.open(io.BytesIO(bg[0].image.blob)).convert("L")
    sx, sy = img.width / 1440, img.height / 810
    title_area = img.crop((int(110 * sx), int(160 * sy), int(500 * sx), int(195 * sy)))
    assert title_area.getextrema()[1] < 235           # no white title letters left in the picture
    assert b'noMove="1"' in bg[0]._element.xml.encode()


def test_portrait_pages_make_portrait_slides(api, files):
    _, data = api.roundtrip(fx.text_pdf(files, pages=2), "pptx")
    prs = slides_of(data)
    assert len(prs.slides) == 2
    assert abs(prs.slide_width / prs.slide_height - 595 / 842) < 0.01
    assert fx.PDF_TEXT in slide_text(prs.slides[0])


@needs_tesseract
def test_with_ocr_scanned_page_text_becomes_editable_text(api, files):
    body, data = api.roundtrip(fx.scanned_page_pdf(files), "pptx-ocr")
    assert body["download_id"].endswith(".pptx")
    assert body["ocr_mode"] == "tesseract"
    assert fx.OCR_WORD in slide_text(slides_of(data).slides[0]).upper()


def test_without_ocr_a_scan_stays_a_picture_with_a_hint(api, files):
    body, data = api.roundtrip(fx.scanned_page_pdf(files), "pptx")
    slide = slides_of(data).slides[0]
    assert body.get("ocr_mode") is None
    assert text_boxes(slide) == [] and len(pictures(slide)) == 1
    assert "with OCR" in body["warning"]


def test_with_ocr_pages_that_have_text_keep_their_own_text(api, files):
    body, data = api.roundtrip(canva_like_pdf(files), "pptx-ocr")
    assert body.get("ocr_mode") is None          # nothing to recognise
    assert "Lesson slide 1" in slide_text(slides_of(data).slides[0])


def two_column_scan_pdf(directory):
    """A scanned page with two columns that Tesseract reads as one line each."""
    import fitz
    from PIL import Image, ImageDraw
    png = directory / "columns.png"
    img = Image.new("RGB", (1700, 600), "white")
    draw = ImageDraw.Draw(img)
    for i in range(3):
        draw.text((60, 60 + i * 120), "Supplier delivered", fill="black", font=fx._font())
        draw.text((960, 60 + i * 120), "customer paid cash", fill="black", font=fx._font())
    img.save(png)
    path = directory / "columns.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_image(fitz.Rect(40, 60, 555, 242), filename=str(png))
    doc.save(str(path))
    doc.close()
    return path


@needs_tesseract
def test_with_ocr_each_column_keeps_its_own_place(api, files):
    _, data = api.roundtrip(two_column_scan_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    pt = prs.slide_width / 595
    right = [b for b in text_boxes(prs.slides[0]) if "customer" in b.text_frame.text]
    assert len(right) == 3
    assert all("Supplier" not in b.text_frame.text and b.left / pt > 300 for b in right)


@needs_tesseract
def test_with_ocr_a_coloured_title_is_recognised(api, files):
    _, data = api.roundtrip(fx.canva_scan_pdf(files), "pptx-ocr")
    assert fx.CANVA_TITLE in slide_text(slides_of(data).slides[0])


@needs_tesseract
def test_with_ocr_an_english_word_in_ukrainian_text_stays_latin(api, files):
    _, data = api.roundtrip(fx.canva_scan_pdf(files), "pptx-ocr")
    assert fx.CANVA_LATIN_LINE in slide_text(slides_of(data).slides[0])


def runs_of(slide):
    return [r for b in text_boxes(slide) for p in b.text_frame.paragraphs for r in p.runs if r.text.strip()]


def test_bold_is_seen_in_a_font_that_does_not_say_it(api, files):
    """Canva exports fonts without names or weights ("Unnamed-T3"); bold is
    then read from how thick the letters are, word by word."""
    _, data = api.roundtrip(fx.unnamed_font_pdf(files), "pptx")
    runs = runs_of(slides_of(data).slides[0])
    assert [(r.text.strip(), bool(r.font.bold)) for r in runs] == [("Спікер", False), (fx.CANVA_BOLD_NAME, True)]


@needs_tesseract
def test_with_ocr_bold_words_stay_bold(api, files):
    _, data = api.roundtrip(fx.canva_scan_pdf(files), "pptx-ocr")
    weight = {r.text.strip(): bool(r.font.bold) for r in runs_of(slides_of(data).slides[0])}
    assert weight[fx.CANVA_BOLD_NAME] and not weight["Спікер"] and weight[fx.CANVA_TITLE]
