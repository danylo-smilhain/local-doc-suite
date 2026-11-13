"""PDF -> DOCX (layout): blocks and lines of a text page are shapes of their
own in Word, not one picture of the whole page."""
import io
import re
import zipfile

import fixtures as fx
import pytest

WORD_TOOLS = pytest.mark.parametrize("target", ["docx", "docx-ocr"])   # "PDF to Word", "... (with OCR)"

EMU_PER_PT = 12700


def anchored(data: bytes, mark: str) -> list[tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) in points of every object of a DOCX whose XML holds mark."""
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    found = []
    for anchor in re.findall(r"<wp:anchor .*?</wp:anchor>", xml):
        if mark not in anchor:
            continue
        x, y = (int(v) / EMU_PER_PT for v in re.findall(r"<wp:posOffset>(-?\d+)</wp:posOffset>", anchor))
        cx, cy = (int(v) / EMU_PER_PT for v in re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"', anchor).groups())
        found.append((x, y, x + cx, y + cy))
    return found


def blocks_of(data: bytes) -> list[tuple[float, float, float, float]]:
    """Filled block shapes (text boxes have txBox="1")."""
    return anchored(data, "<wps:cNvSpPr/>")


def near(box, want, tol=1):
    return all(abs(a - b) <= tol for a, b in zip(box, want))


@WORD_TOOLS
def test_a_block_filled_and_outlined_separately_is_a_shape(api, files, target):
    """PowerPoint fills a block and then outlines it with a second operator;
    the page's graphics were left as one picture with the warning that the
    drawings did not match."""
    body, data = api.roundtrip(fx.outlined_band_pdf(files), target)
    assert body["engine"] == "layout"
    assert body["warnings"] == []
    assert any(near(box, fx.OUTLINED_BAND) for box in blocks_of(data)), blocks_of(data)
