"""PDF -> PPTX: what a slide is made of besides its text. Photos, screenshots,
logos, bars and blocks become their own pictures and shapes on the slide, in
the places and order the PDF draws them; text hidden in the PDF stays out;
text keeps within the width it had. Built on a Canva-like lesson deck
(fixtures.canva_lesson_pdf)."""
import fixtures as fx
from conftest import needs_tesseract
from test_pdf_to_pptx import PICTURE, slide_text, slides_of, text_boxes

AUTO_SHAPE = 1   # MSO_SHAPE_TYPE.AUTO_SHAPE


def placed(prs, shape, page_w=1440):
    """(x0, y0, x1, y1) of a shape in PDF points."""
    pt = prs.slide_width / page_w
    return (shape.left / pt, shape.top / pt, (shape.left + shape.width) / pt, (shape.top + shape.height) / pt)


def near(box, want, tol=4):
    return all(abs(a - b) <= tol for a, b in zip(box, want))


def objects(slide):
    return [s for s in slide.shapes if not (s.has_text_frame and s.text_frame.text.strip())]


def test_photo_logo_and_bar_are_their_own_objects(api, files):
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    boxes = [(s.shape_type, placed(prs, s)) for s in objects(prs.slides[0])]
    assert any(t == PICTURE and near(b, fx.LESSON_PHOTO) for t, b in boxes)
    assert any(t == PICTURE and near(b, fx.LESSON_LOGO) for t, b in boxes)
    assert any(near(b, fx.LESSON_LINE) for t, b in boxes)
    assert any(near(b, fx.LESSON_BLOCK) for t, b in boxes)
    assert any(near(b, fx.LESSON_ICON) for t, b in boxes)


def test_objects_lie_under_the_text(api, files):
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    shapes = list(slides_of(data).slides[0].shapes)
    first_text = next(i for i, s in enumerate(shapes) if s.has_text_frame and s.text_frame.text.strip())
    assert all(not (s.has_text_frame and s.text_frame.text.strip()) or i >= first_text
               for i, s in enumerate(shapes)) and len(objects(slides_of(data).slides[0])) >= 5
    assert first_text >= 5


def test_the_background_stays_put_and_the_objects_can_be_moved(api, files):
    """The slide's background (page colour, texture, card) is one picture
    locked over the whole slide; photos, logos and screenshots, a big one
    included, can be moved."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    for slide in (prs.slides[0], prs.slides[3]):
        locked = [placed(prs, s) for s in objects(slide) if b'noMove="1"' in s._element.xml.encode()]
        assert len(locked) == 1 and near(locked[0], (0, 0, 1440, 810), tol=1)
        assert len(objects(slide)) >= 2


def test_moving_a_photo_shows_the_card_not_a_copy_of_the_photo(api, files):
    import io

    from PIL import Image
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    back = next(s for s in objects(prs.slides[0]) if b'noMove="1"' in s._element.xml.encode())
    img = Image.open(io.BytesIO(back.image.blob)).convert("RGB")
    s = img.width / 1440
    x0, y0, x1, _ = fx.LESSON_PHOTO
    r, g, b = img.getpixel((int((x0 + x1) / 2 * s), int((y0 + 40) * s)))     # the photo's pink top
    assert min(r, g, b) > 200                                                    # white card there


def test_the_card_stays_white_around_a_round_picture_on_its_corner(api, files):
    """Only what an object covers is filled in under it: around a circle on
    the card's corner the card keeps its colour (it turned the colour of the
    border all over the circle's square)."""
    import io

    from PIL import Image
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    back = next(s for s in objects(prs.slides[0]) if b'noMove="1"' in s._element.xml.encode())
    img = Image.open(io.BytesIO(back.image.blob)).convert("RGB")
    s = img.width / 1440
    (cx, cy), r = fx.LESSON_BADGE
    corner = (cx - 0.9 * r, cy + 0.9 * r)          # in the circle's square, outside it, on the card
    assert min(img.getpixel((int(corner[0] * s), int(corner[1] * s)))) > 235


def test_text_covered_by_the_background_is_left_out(api, files):
    """The template's name lies under the background; the same name drawn
    again on top in the same place stays."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    text = slide_text(slides_of(data).slides[0])
    assert fx.LESSON_SPEAKER in text and fx.LESSON_TITLE in text
    assert text.count(fx.LESSON_HIDDEN) == 1


def written_width(run, k):
    """Width in PDF points of a run as PowerPoint writes it: its font (the
    substitute's metrics), size and letter spacing."""
    from app.pdf_layout import _FONT_FAMILIES, _metric_font
    fam = next(f for f, (name, *_) in _FONT_FAMILIES.items() if name == run.font.name)
    size = run.font.size.pt / k
    spacing = int(run.font._rPr.get("spc", "0")) / 100 / k
    return _metric_font(fam, bool(run.font.bold), bool(run.font.italic)).text_length(run.text, fontsize=size) \
        + spacing * len(run.text)


def test_text_keeps_within_the_width_it_had(api, files):
    """Canva's narrow font replaced by a wider one must not run out of its block."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    k = prs.slide_width / 1440 / 12700                     # slide points per PDF point
    box = next(b for b in text_boxes(prs.slides[0]) if fx.LESSON_BLOCK_TEXT in b.text_frame.text)
    run = box.text_frame.paragraphs[0].runs[0]
    assert placed(prs, box)[0] + written_width(run, k) <= fx.LESSON_BLOCK[2] - 5


def test_with_ocr_a_slide_of_screenshots_is_not_a_scan(api, files):
    """A slide without text is not a scan: its screenshots stay pictures, the
    words in their pixels are not made into text."""
    body, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx-ocr")
    prs = slides_of(data)
    slide = prs.slides[1]
    assert fx.LESSON_PHONE_TEXT not in slide_text(slide) and body.get("ocr_mode") is None
    boxes = [placed(prs, s) for s in objects(slide) if s.shape_type == PICTURE]
    assert all(any(near(b, phone) for b in boxes) for phone in fx.LESSON_PHONES)


def test_a_link_is_text_not_a_damaged_text_layer(api, files):
    body, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    slide = slides_of(data).slides[2]
    text = slide_text(slide)
    assert all(line in text for line in fx.LESSON_URL)
    runs = [r for b in text_boxes(slide) for p in b.text_frame.paragraphs for r in p.runs
            if r.text.strip() in fx.LESSON_URL]
    assert len(runs) == len(fx.LESSON_URL) and all(r.font.underline for r in runs)   # the line under it
    assert not body.get("warning")


def test_a_slide_with_one_big_screenshot_is_not_a_scan(api, files):
    """A screenshot over 60% of a text-less slide is a picture on the slide,
    not a scanned page."""
    body, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    boxes = [placed(prs, s) for s in objects(prs.slides[3]) if s.shape_type == PICTURE]
    assert any(near(b, fx.LESSON_BIG_SHOT) for b in boxes)
    assert not body.get("warning")


def test_no_text_is_left_in_the_pictures(api, files):
    """Every line of a block of text becomes a text box, none stays drawn in
    a picture under it (the first and last lines of a list did)."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    assert all(line in slide_text(prs.slides[0]) for line in fx.LESSON_LIST)
    lines = [b for b in text_boxes(prs.slides[0]) if b.text_frame.text in fx.LESSON_LIST]
    for s in objects(prs.slides[0]):
        x0, y0, x1, y1 = placed(prs, s)
        if (x1 - x0) * (y1 - y0) < 0.5 * 1440 * 810:            # not the background
            assert not any(x0 <= placed(prs, b)[0] + 5 and y0 <= placed(prs, b)[1] + 10 <= y1 for b in lines), s.name


def test_a_nearly_opaque_picture_is_stored_without_transparency(api, files):
    """A phone (screenshot in a frame with rounded corners) is mostly opaque:
    kept as a plain image, a transparent PNG of it was several megabytes;
    the sparse logo keeps its transparency."""
    import io

    from PIL import Image
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    phones = [s for s in objects(prs.slides[1]) if any(near(placed(prs, s), p, tol=16) for p in fx.LESSON_PHONES)]
    logo = next(s for s in objects(prs.slides[0]) if near(placed(prs, s), fx.LESSON_LOGO))
    has_alpha = lambda s: "A" in Image.open(io.BytesIO(s.image.blob)).convert("RGBA").getbands() and \
        Image.open(io.BytesIO(s.image.blob)).mode in ("RGBA", "LA", "PA") or \
        "transparency" in Image.open(io.BytesIO(s.image.blob)).info
    assert len(phones) == 3 and not any(has_alpha(s) for s in phones)
    assert has_alpha(logo)


def test_a_photo_beside_a_half_slide_panel_is_its_own_picture(api, files):
    """A panel over half the slide is background; the photo 7 pt from it is
    not glued to it into one slide-sized picture."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    prs = slides_of(data)
    boxes = [placed(prs, s) for s in objects(prs.slides[4]) if s.shape_type == PICTURE]
    assert any(near(b, fx.LESSON_SIDE_PHOTO) for b in boxes)


def test_text_under_the_cut_off_part_of_a_picture_is_kept(api, files):
    """A picture drawn after a caption, whose frame covers it but whose crop
    stops above it, does not hide the caption."""
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    assert fx.LESSON_CAPTION in slide_text(slides_of(data).slides[4])


def test_an_underlined_space_stays_between_its_words(api, files):
    _, data = api.roundtrip(fx.canva_lesson_pdf(files), "pptx")
    assert fx.LESSON_SPACED in slide_text(slides_of(data).slides[2])
