"""MOBI (Kindle) -> EPUB / AZW3 / PDF / MD.

The fixture is a real MOBI book made by Calibre from the EPUB fixture, so
these tests need ebook-convert (installed in the Docker image and in CI).
"""
import pytest

import fixtures as fx
from conftest import is_epub, is_pdf, needs_calibre, needs_libreoffice, needs_pandoc


@needs_calibre
def test_mobi_to_epub(api, files):
    _, data = api.roundtrip(fx.mobi(files), "epub")
    assert is_epub(data)


@needs_calibre
@needs_pandoc
def test_mobi_to_md(api, files):
    _, data = api.roundtrip(fx.mobi(files), "md")
    assert fx.EPUB_TEXT in data.decode("utf-8")


@needs_calibre
@needs_libreoffice
def test_mobi_to_pdf(api, files):
    _, data = api.roundtrip(fx.mobi(files), "pdf")
    assert is_pdf(data)


@needs_calibre
@needs_pandoc
def test_mobi_to_azw3_is_a_readable_kindle_book(api, files):
    body, data = api.roundtrip(fx.mobi(files), "azw3")
    assert body["engine"] == "calibre"
    assert data[60:68] == b"BOOKMOBI"
    # The result opens again as AZW3 and still has the book's text.
    azw3 = files / "result.azw3"
    azw3.write_bytes(data)
    _, md = api.roundtrip(azw3, "md")
    assert fx.EPUB_TEXT in md.decode("utf-8")


@needs_calibre
def test_mobi_metadata_counts_words(api, files):
    assert api.upload(fx.mobi(files))["meta"]["words"] > 5


@needs_calibre
def test_mobi_to_unsupported_target_is_422(api, files):
    res = api.convert(api.upload(fx.mobi(files)), "txt")
    assert res.status_code == 422
    assert "MOBI cannot be converted to TXT" in res.json()["detail"]


@pytest.mark.parametrize("target", ["epub", "azw3"])
def test_mobi_with_drm_is_422(api, files, target):
    res = api.convert(api.upload(fx.azw3_drm(files, "drm.mobi")), target)
    assert res.status_code == 422


def test_other_formats_to_azw3_is_422(api, files):
    res = api.convert(api.upload(fx.docx(files)), "azw3")
    assert res.status_code == 422
    assert res.json()["code"] == "UNSUPPORTED_CONVERSION"
