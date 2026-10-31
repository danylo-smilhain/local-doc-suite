"""AZW3 (Kindle) -> EPUB / PDF / MD through an unpacked EPUB.

The fixture is an EPUB saved as .azw3, which the backend handles without
Calibre or KindleUnpack ("copy" engine). Real KF8 files need ebook-convert.
"""
import shutil

import pytest

import fixtures as fx
from conftest import is_epub, is_pdf, needs_libreoffice, needs_pandoc


def test_azw3_to_epub(api, files):
    _, data = api.roundtrip(fx.azw3_renamed_epub(files), "epub")
    assert is_epub(data)


@needs_pandoc
def test_azw3_to_md(api, files):
    _, data = api.roundtrip(fx.azw3_renamed_epub(files), "md")
    assert fx.EPUB_TEXT in data.decode("utf-8")


@needs_libreoffice
def test_azw3_to_pdf(api, files):
    _, data = api.roundtrip(fx.azw3_renamed_epub(files), "pdf")
    assert is_pdf(data)


def test_azw3_to_unsupported_target_is_422(api, files):
    res = api.convert(api.upload(fx.azw3_renamed_epub(files)), "txt")
    assert res.status_code == 422


def test_azw3_with_drm_is_422(api, files):
    res = api.convert(api.upload(fx.azw3_drm(files)), "epub")
    assert res.status_code == 422


@pytest.mark.skipif(shutil.which("ebook-convert") is None,
                    reason="system binary not installed: ebook-convert (Calibre) — needed to build a real KF8 fixture and to unpack it")
def test_real_kf8_azw3_to_epub(api, files):
    import subprocess
    src = fx.epub(files)
    azw3 = files / "real.azw3"
    subprocess.run(["ebook-convert", str(src), str(azw3)], check=True, capture_output=True, timeout=300)
    _, data = api.roundtrip(azw3, "epub")
    assert is_epub(data)
