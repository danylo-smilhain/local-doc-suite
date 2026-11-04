"""A slide that is only a picture (a scan, a NotebookLM / Gemini export, a
damaged PDF read by OCR), split the way a slide drawn by the PDF itself is
(pdf_pptx._split_objects): one locked backdrop and the things on it as
pictures of their own, so a logo, an icon, a line or a block can be moved.

Glossary:
- page colour: the colour most of the slide has;
- ink: the pixels that differ from the page colour;
- an object: ink that holds together over gaps narrower than OBJECT_GAP_PT
  (the four diamonds of a logo, a table with its lines);
- the backdrop: the slide without its objects. What is as big as the slide
  (a frame around it, a texture, a fill over most of it) is part of it, as
  are marks too small to be anything (dust, JPEG noise).
The recognised text is painted out of the picture before it is split
(pdf_pptx._ocr_page), so no object carries text that is also a text box.
"""
import io
from collections import deque

import numpy as np
from PIL import Image

from app.pdf_layout import LAYOUT_SCAN_COVER, _image_bytes, _inpaint_boxes

# Ink differs from the page colour by more than this (0-255) in some channel:
# anti-aliased edges and JPEG noise around the page colour stay page.
INK_CONTRAST = 40
# Parts of one thing closer than this stay one picture: the diamonds of a
# logo, a target's rings, a table's lines. The same gap that keeps two cells'
# text apart (slide_ocr.walled) is drawn, so it holds them.
OBJECT_GAP_PT = 6
# The page colour must cover this share of the slide; a photo or a gradient
# behind everything has none and the slide stays one picture. Ink over the
# same share is a fill behind the rest (a card, a panel over half the slide):
# part of the backdrop, and what lies on it is found the same way, against
# the fill's own colour.
PAGE_COLOUR_SHARE = 0.3
# A thing with less ink than a square of this side is a mark, not an object
# (dust, JPEG noise): what is left of a letter just outside its word box
# (9 x 1 pt) is no object, a thin long line is.
MIN_INK_PT = 5
# A picture this opaque is stored without transparency (as _pieces does).
OPAQUE_PIECE = 0.9


def page_colour(a: np.ndarray, where: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """The colour most of the picture has (RGB array; only where the mask
    says, if given) and the share of those pixels that are that colour (not
    ink against it). The colour is the commonest in 32 levels a channel;
    the share counts every pixel near it, so noise across two levels
    (a JPEG-ed white, 240-255) does not split the page."""
    step = max(1, int(np.sqrt(a.shape[0] * a.shape[1] / 250_000)))
    sample = a[::step, ::step].reshape(-1, 3)
    if where is not None:
        sample = sample[where[::step, ::step].reshape(-1)]
    codes = (sample[:, 0] // 8).astype(int) * 1024 + (sample[:, 1] // 8) * 32 + sample[:, 2] // 8
    top = int(np.bincount(codes, minlength=32768).argmax())
    colour = np.median(sample[codes == top], axis=0)
    return colour, float((np.abs(sample.astype(int) - colour).max(axis=1) <= INK_CONTRAST).mean())


def _labels(cells: np.ndarray) -> tuple[np.ndarray, int]:
    """Connected groups (8 neighbours) of the True cells of a grid: a label
    from 1 per cell, 0 where nothing is; and the number of groups."""
    labels = np.zeros(cells.shape, int)
    count = 0
    h, w = cells.shape
    for y, x in zip(*np.nonzero(cells)):
        if labels[y, x]:
            continue
        count += 1
        labels[y, x] = count
        todo = deque([(y, x)])
        while todo:
            cy, cx = todo.popleft()
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if cells[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = count
                        todo.append((ny, nx))
    return labels, count


def _grow(mask: np.ndarray) -> np.ndarray:
    """The mask one pixel wider all round: an object keeps its soft edge."""
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def objects_of(ink: np.ndarray, gap_px: int, min_ink: int) -> list[np.ndarray]:
    """The objects of an ink mask: one mask each, ink grouped over gaps up to
    gap_px; groups with fewer than min_ink pixels are left out."""
    h, w = ink.shape
    cell = max(1, gap_px)
    ch, cw = -(-h // cell), -(-w // cell)
    padded = np.zeros((ch * cell, cw * cell), bool)
    padded[:h, :w] = ink
    cells = padded.reshape(ch, cell, cw, cell).any(axis=(1, 3))
    labels, count = _labels(cells)
    pixels = np.repeat(np.repeat(labels, cell, axis=0), cell, axis=1)[:h, :w] * ink
    out = []
    for n in range(1, count + 1):
        mask = pixels == n
        ys, xs = np.nonzero(mask)
        if len(xs) >= max(1, min_ink):
            out.append(mask)
    return out


def is_fill(mask: np.ndarray) -> bool:
    """Ink over a large share of the slide: a fill behind the rest."""
    return mask.sum() >= PAGE_COLOUR_SHARE * mask.size


def spans_slide(mask: np.ndarray) -> bool:
    """Ink whose extent covers the slide: a frame around it, a texture."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    return (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1) >= LAYOUT_SCAN_COVER * h * w


def things_on(rgb: np.ndarray, colour: np.ndarray, region: np.ndarray, sizes: tuple[int, int],
              nested: bool) -> list[np.ndarray]:
    """The objects lying on one colour of the backdrop (in region): ink that
    differs from it, grouped (objects_of). A fill as big as a page colour is
    backdrop too; once (nested) the things on it are looked for against its
    own colour. Frames and textures across the slide stay backdrop. sizes:
    objects_of's gap and least ink, in pixels."""
    ink = region & (np.abs(rgb.astype(int) - colour).max(axis=2) > INK_CONTRAST)
    out = []
    for mask in objects_of(ink, *sizes):
        if is_fill(mask):
            if nested:
                fill, _ = page_colour(rgb, mask)
                out += things_on(rgb, fill, mask, sizes, nested=False)
        elif not spans_slide(mask):
            out.append(mask)
    return out


def _picture(rgb: np.ndarray, mask: np.ndarray, box, size: tuple[int, int]) -> bytes:
    """One object as an image: its own pixels, transparent around them unless
    it is nearly all opaque (a photo, a block: stored flat, much smaller)."""
    x0, y0, x1, y1 = box
    alpha = _grow(mask)[y0:y1, x0:x1]
    part = Image.fromarray(rgb[y0:y1, x0:x1])
    if alpha.mean() >= OPAQUE_PIECE:
        return _image_bytes(part.resize(size, Image.LANCZOS) if size != part.size else part)
    rgba = part.convert("RGBA")
    rgba.putalpha(Image.fromarray(alpha.astype(np.uint8) * 255))
    if size != rgba.size:
        rgba = rgba.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    rgba.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def split_picture(img: Image.Image, scale_pt: float, out_scale_pt: float) -> list[dict] | None:
    """A slide picture (text already painted out) as its backdrop and its
    objects, bottom to top, for pdf_pptx._add_object: places in points
    (scale_pt points per pixel of img); the images are stored at out_scale_pt
    points per pixel when that is coarser. None: the slide has no page colour
    (a photo behind everything) or nothing on it; it stays one picture."""
    rgb = np.asarray(img.convert("RGB"))
    colour, share = page_colour(rgb)
    if share < PAGE_COLOUR_SHARE:
        return None
    h, w = rgb.shape[:2]
    sizes = (round(OBJECT_GAP_PT / scale_pt), round((MIN_INK_PT / scale_pt) ** 2))
    masks = things_on(rgb, colour, np.ones((h, w), bool), sizes, nested=True)
    if not masks:
        return None
    masks.sort(key=lambda m: (np.nonzero(m)[0].min(), np.nonzero(m)[1].min()))
    shrink = min(1.0, scale_pt / out_scale_pt)
    objects, covered, boxes = [], np.zeros((h, w), bool), []
    for n, mask in enumerate(masks, 1):
        ys, xs = np.nonzero(mask)
        box = (max(0, xs.min() - 1), max(0, ys.min() - 1), min(w, xs.max() + 2), min(h, ys.max() + 2))
        size = (max(1, round((box[2] - box[0]) * shrink)), max(1, round((box[3] - box[1]) * shrink)))
        objects.append({"kind": "pic", "img": _picture(rgb, mask, box, size), "name": f"Picture {n}",
                        "x": box[0] * scale_pt, "y": box[1] * scale_pt,
                        "w": (box[2] - box[0]) * scale_pt, "h": (box[3] - box[1]) * scale_pt})
        covered |= _grow(mask)
        boxes.append(box)
    # under each object the backdrop takes the colour around it, only where
    # the object has pixels (as in _split_objects)
    filled = np.asarray(_inpaint_boxes(Image.fromarray(rgb), boxes))
    backdrop = Image.fromarray(np.where(covered[:, :, None], filled, rgb))
    if shrink < 1:
        backdrop = backdrop.resize((max(1, round(w * shrink)), max(1, round(h * shrink))), Image.LANCZOS)
    return [{"kind": "pic", "img": _image_bytes(backdrop), "x": 0.0, "y": 0.0, "w": w * scale_pt,
             "h": h * scale_pt, "name": "Background", "backdrop": True}] + objects
