"""A slide that is only a picture, split into its backdrop and the things on
it (app.slide_raster), on small drawn pictures."""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw


@pytest.fixture(scope="module")
def sr(app):
    from app import slide_raster
    return slide_raster


def page(w=400, h=200, fill="white"):
    img = Image.new("RGB", (w, h), fill)
    return img, ImageDraw.Draw(img)


def split(sr, img):
    """split_picture at 1 pt per pixel: (name, (x0, y0, x1, y1)) of each picture."""
    out = sr.split_picture(img, 1.0, 1.0)
    return None if out is None else [(o["name"], (o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"])) for o in out]


def test_the_page_colour_is_the_one_most_of_the_slide_has(sr):
    img, d = page()
    d.rectangle((0, 0, 150, 199), fill=(250, 220, 195))
    colour, share = sr.page_colour(np.asarray(img))
    assert tuple(colour) == (255, 255, 255) and 0.6 < share < 0.65


def test_each_thing_on_the_page_is_its_own_picture_over_the_backdrop(sr):
    img, d = page()
    d.rectangle((20, 20, 60, 60), fill="black")              # a logo
    d.rectangle((200, 100, 380, 104), fill=(170, 11, 10))   # a line
    parts = split(sr, img)
    assert parts[0] == ("Background", (0, 0, 400, 200))
    assert sorted(b for _, b in parts[1:]) == [(19, 19, 62, 62), (199, 99, 382, 106)]


def test_parts_closer_than_the_gap_are_one_picture(sr):
    """The diamonds of a logo, a 4 px gap: one picture; 20 px apart: two."""
    img, d = page()
    d.rectangle((20, 20, 40, 40), fill="black")
    d.rectangle((45, 20, 65, 40), fill="black")
    d.rectangle((86, 20, 106, 40), fill="black")
    assert sorted(b for _, b in split(sr, img)[1:]) == [(19, 19, 67, 42), (85, 19, 108, 42)]


def test_what_is_as_big_as_the_slide_stays_in_its_backdrop(sr):
    """A frame around the slide and a fill over half of it are its backdrop;
    what lies on the fill or on the rest of the page is an object."""
    img, d = page()
    d.rectangle((0, 0, 399, 199), outline=(77, 168, 176), width=6)
    assert split(sr, img) is None
    img, d = page()
    d.rectangle((0, 0, 260, 199), fill=(30, 90, 100))       # the page colour now
    d.ellipse((300, 50, 340, 90), fill="black")              # on the white rest
    d.rectangle((40, 40, 80, 80), fill="white")              # on the panel
    assert sorted(b for _, b in split(sr, img)[1:]) == [(39, 39, 82, 82), (299, 49, 342, 92)]


def test_dust_stays_in_the_backdrop(sr):
    img, d = page()
    d.point((100, 100), fill="black")
    d.rectangle((200, 50, 201, 51), fill="black")
    assert split(sr, img) is None


def test_a_photo_behind_everything_leaves_the_slide_one_picture(sr):
    rnd = np.random.default_rng(3)
    img = Image.fromarray(rnd.integers(0, 255, (200, 400, 3), dtype=np.uint8))
    assert split(sr, img) is None


def test_under_an_object_the_backdrop_takes_the_colour_around_it(sr):
    img, d = page(fill=(250, 220, 195))
    d.ellipse((100, 50, 160, 110), fill="black")
    back = Image.open(io.BytesIO(sr.split_picture(img, 1.0, 1.0)[0]["img"])).convert("RGB")
    r, g, b = back.getpixel((130, 80))
    assert abs(r - 250) < 8 and abs(g - 220) < 8 and abs(b - 195) < 8


def test_a_round_thing_is_transparent_around_it_and_a_block_is_stored_flat(sr):
    img, d = page()
    d.ellipse((20, 20, 80, 80), fill="black")
    d.rectangle((200, 50, 300, 150), fill=(250, 220, 195))
    pics = sr.split_picture(img, 1.0, 1.0)[1:]
    circle, block = sorted(pics, key=lambda o: o["x"])
    corner = Image.open(io.BytesIO(circle["img"]))
    assert corner.mode == "RGBA" and corner.getpixel((1, 1))[3] == 0
    flat = Image.open(io.BytesIO(block["img"]))
    assert flat.mode in ("RGB", "P") and "transparency" not in flat.info


def test_pictures_are_stored_no_finer_than_asked(sr):
    """Read at 2 pt-pixels per point, stored at 1: half the pixels, same place."""
    img, d = page(800, 400)
    d.rectangle((100, 100, 300, 140), fill="black")
    logo = sr.split_picture(img, 0.5, 1.0)[1]
    assert Image.open(io.BytesIO(logo["img"])).size == (102, 22)
    assert (logo["x"], logo["y"], logo["w"], logo["h"]) == (49.5, 49.5, 101.5, 21.5)


def test_a_scrap_of_a_letter_stays_in_the_backdrop_a_thin_line_does_not(sr):
    """What is left of a letter just outside its word box (9 x 1 pt) is no
    object; a rule as thin but long is."""
    img, d = page()
    d.rectangle((20, 20, 28, 20), fill="black")
    d.rectangle((20, 100, 220, 100), fill="black")
    assert [b for _, b in split(sr, img)[1:]] == [(19, 99, 222, 102)]


def test_noise_around_the_page_colour_stays_page(sr):
    """A JPEG-ed white page is 240-255, not 255: that is no ink."""
    rnd = np.random.default_rng(5)
    img = Image.fromarray((255 - rnd.integers(0, 16, (200, 400, 3))).astype(np.uint8))
    ImageDraw.Draw(img).rectangle((20, 20, 60, 60), fill="black")
    assert [b for _, b in split(sr, img)[1:]] == [(19, 19, 62, 62)]


def test_an_object_takes_its_soft_edge_along(sr):
    """A pixel of anti-aliased edge too light to be ink goes with the object,
    and the backdrop keeps no ring of it."""
    img, d = page()
    d.rectangle((99, 49, 161, 111), fill=(225, 225, 225))     # the soft edge
    d.rectangle((100, 50, 160, 110), fill="black")
    back, logo = sr.split_picture(img, 1.0, 1.0)
    pic = Image.open(io.BytesIO(logo["img"])).convert("RGBA")
    assert pic.getpixel((0, 30))[3] == 255                      # x 99: the edge, in the picture
    assert Image.open(io.BytesIO(back["img"])).convert("RGB").getpixel((99, 80)) == (255, 255, 255)
