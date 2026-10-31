"""PPTX -> PDF works (LibreOffice). PPTX -> DOCX / MD are offered by the UI but
fail in the original backend (pandoc cannot read PPTX). Pinned as-is."""
import pytest

import fixtures as fx
from conftest import is_pdf, needs_libreoffice, pdf_text


@needs_libreoffice
def test_pptx_to_pdf(api, files):
    _, data = api.roundtrip(fx.pptx(files), "pdf")
    assert is_pdf(data)
    assert fx.PPTX_TITLE in pdf_text(data)


@pytest.mark.parametrize("target", ["docx", "md"])
def test_pptx_to_pandoc_target_fails_with_500(api, files, target):
    res = api.convert(api.upload(fx.pptx(files)), target)
    assert res.status_code == 500
