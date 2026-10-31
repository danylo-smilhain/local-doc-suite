"""Image -> TXT / MD ("Image to TXT", "Image to Markdown" tools).

Images are OCRed through Tesseract (app.convert.image_to_text)."""
import pytest

import fixtures as fx
from conftest import needs_tesseract

pytestmark = needs_tesseract


@pytest.mark.parametrize("target", ["txt", "md"])
def test_image_ocr_returns_recognised_text(api, files, target):
    body, data = api.roundtrip(fx.text_image(files), target)
    assert body["engine"] == "tesseract"
    assert fx.OCR_WORD in data.decode("utf-8").upper()
