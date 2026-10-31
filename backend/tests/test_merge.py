"""Merging several uploads (file_id is a comma-separated list)."""
import pytest

import fixtures as fx
from conftest import (docx_text, is_docx, is_epub, is_fb2, is_pdf, needs_libreoffice,
                      needs_pandoc, pdf_text)


def two(api, make, files):
    return [api.upload(make(files, f"part{i}")) for i in (1, 2)]


def merged(api, uploads, target):
    body = api.convert_ok(uploads, target)
    assert body["download_id"].startswith("merged_")
    return body, api.download_bytes(body["download_id"])


def named(builder, ext):
    return lambda d, stem: builder(d, f"{stem}.{ext}")


def test_merge_pdf(api, files):
    uploads = [api.upload(fx.text_pdf(files, "a.pdf", text="Alpha")), api.upload(fx.text_pdf(files, "b.pdf", text="Beta"))]
    body, data = merged(api, uploads, "pdf")
    assert is_pdf(data)
    assert body["meta"]["pages"] == 2
    text = pdf_text(data)
    assert text.index("Alpha") < text.index("Beta")


def test_merge_docx(api, files):
    uploads = [api.upload(fx.docx(files, "a.docx", text="First doc")), api.upload(fx.docx(files, "b.docx", text="Second doc"))]
    _, data = merged(api, uploads, "docx")
    assert is_docx(data)
    xml = docx_text(data)
    assert xml.index("First doc") < xml.index("Second doc")


def test_merge_txt(api, files):
    uploads = [api.upload(fx.txt(files, "a.txt", text="one")), api.upload(fx.txt(files, "b.txt", text="two"))]
    _, data = merged(api, uploads, "txt")
    assert data.decode("utf-8") == "one\n\ntwo\n"


def test_merge_md(api, files):
    uploads = two(api, named(fx.markdown, "md"), files)
    _, data = merged(api, uploads, "md")
    assert data.decode("utf-8").count("# Notes heading") == 2


def test_merge_html(api, files):
    uploads = two(api, named(fx.html, "html"), files)
    _, data = merged(api, uploads, "html")
    assert data.decode("utf-8").count(fx.HTML_TEXT) == 2


def test_merge_txt_to_md_uses_rule_separator(api, files):
    uploads = [api.upload(fx.txt(files, "a.txt", text="first part")), api.upload(fx.txt(files, "b.txt", text="second part"))]
    _, data = merged(api, uploads, "md")
    assert data.decode("utf-8") == "first part\n\n---\n\nsecond part\n"


@needs_pandoc
def test_merge_docx_to_md(api, files):
    uploads = [api.upload(fx.docx(files, "a.docx", text="First doc")), api.upload(fx.docx(files, "b.docx", text="Second doc"))]
    _, data = merged(api, uploads, "md")
    text = data.decode("utf-8")
    assert text.index("First doc") < text.index("Second doc")


def test_merge_pdf_to_md(api, files):
    uploads = [api.upload(fx.text_pdf(files, "a.pdf", text="Alpha")), api.upload(fx.text_pdf(files, "b.pdf", text="Beta"))]
    _, data = merged(api, uploads, "md")
    text = data.decode("utf-8")
    assert text.index("Alpha") < text.index("Beta")


@needs_pandoc
def test_merge_html_to_md(api, files):
    uploads = two(api, named(fx.html, "html"), files)
    _, data = merged(api, uploads, "md")
    text = data.decode("utf-8")
    assert text.count(fx.HTML_TEXT) == 2
    assert "<div" not in text


def test_merge_telegram_to_md_keeps_one_title(api, files):
    uploads = [api.upload(fx.telegram_html(files, "m1.html", "first message")),
               api.upload(fx.telegram_html(files, "m2.html", "second message"))]
    _, data = merged(api, uploads, "md")
    text = data.decode("utf-8")
    assert text.count(f"# {fx.TELEGRAM_CHAT}") == 1
    assert text.index("first message") < text.index("second message")


@needs_libreoffice
def test_merge_html_to_pdf(api, files):
    uploads = two(api, named(fx.html, "html"), files)
    _, data = merged(api, uploads, "pdf")
    assert is_pdf(data)
    assert pdf_text(data).count(fx.HTML_TEXT) == 2


@needs_pandoc
@needs_libreoffice
def test_merge_telegram_to_pdf(api, files):
    uploads = [api.upload(fx.telegram_html(files, "m1.html", "first message")),
               api.upload(fx.telegram_html(files, "m2.html", "second message"))]
    _, data = merged(api, uploads, "pdf")
    assert is_pdf(data)
    text = pdf_text(data)
    assert "first message" in text and "second message" in text


@needs_libreoffice
@pytest.mark.parametrize("builder,ext", [(fx.docx, "docx"), (fx.pptx, "pptx")])
def test_merge_office_to_pdf(api, files, builder, ext):
    uploads = two(api, named(builder, ext), files)
    body, data = merged(api, uploads, "pdf")
    assert is_pdf(data)
    assert body["meta"]["pages"] == 2


@needs_pandoc
def test_merge_epub(api, files):
    uploads = [api.upload(fx.epub(files, "a.epub", title="Alpha", text="first book")),
               api.upload(fx.epub(files, "b.epub", title="Beta", text="second book"))]
    _, data = merged(api, uploads, "epub")
    assert is_epub(data)


@needs_pandoc
def test_merge_fb2(api, files):
    uploads = [api.upload(fx.fb2(files, "a.fb2", text="first book")), api.upload(fx.fb2(files, "b.fb2", text="second book"))]
    _, data = merged(api, uploads, "fb2")
    assert is_fb2(data)
    assert data.index(b"first book") < data.index(b"second book")


@needs_pandoc
def test_merge_epub_to_md(api, files):
    uploads = [api.upload(fx.epub(files, "a.epub", text="first book")), api.upload(fx.epub(files, "b.epub", text="second book"))]
    _, data = merged(api, uploads, "md")
    text = data.decode("utf-8")
    assert text.index("first book") < text.index("second book")


def test_merge_pptx_fails_with_500(api, files):
    """Offered by the UI ("Merge PPTX") but broken in the original backend:
    pptx is read as text and handed to pandoc. Pinned as-is; see NOTES.md."""
    uploads = two(api, named(fx.pptx, "pptx"), files)
    assert api.convert(uploads, "pptx").status_code == 500
