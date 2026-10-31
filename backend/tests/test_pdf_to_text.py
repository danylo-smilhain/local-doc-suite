"""PDF -> TXT / MD via the text-layer extractor."""
import fixtures as fx


def test_pdf_to_txt(api, files):
    body, data = api.roundtrip(fx.text_pdf(files), "txt")
    assert body["download_id"].endswith(".txt")
    assert fx.PDF_TEXT in data.decode("utf-8")


def test_pdf_to_md(api, files):
    body, data = api.roundtrip(fx.text_pdf(files), "md")
    assert body["download_id"].endswith(".md")
    assert fx.PDF_TEXT in data.decode("utf-8")
