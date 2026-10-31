"""PDF -> EPUB / FB2 / PPTX are offered by the UI but fail in the original
backend (pandoc cannot read PDF). Pinned as-is; see NOTES.md (open questions)."""
import pytest

import fixtures as fx


@pytest.mark.parametrize("target", ["epub", "fb2", "pptx"])
def test_pdf_to_pandoc_target_fails_with_500(api, files, target):
    res = api.convert(api.upload(fx.text_pdf(files)), target)
    assert res.status_code == 500
