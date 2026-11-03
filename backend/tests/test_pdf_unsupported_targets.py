"""PDF -> EPUB / FB2 are offered by the UI but still fail as in the original
backend (pandoc cannot read PDF). Pinned as-is. PDF -> PPTX has its own
converter now (test_pdf_to_pptx.py)."""
import pytest

import fixtures as fx


@pytest.mark.parametrize("target", ["epub", "fb2"])
def test_pdf_to_pandoc_target_fails_with_500(api, files, target):
    res = api.convert(api.upload(fx.text_pdf(files)), target)
    assert res.status_code == 500
