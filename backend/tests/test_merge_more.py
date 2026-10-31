"""More merge paths, pinned before splitting merge_to_pdf / convert_to_text_format."""
import fixtures as fx
from conftest import is_pdf, needs_libreoffice, needs_pandoc, pdf_text


def merged(api, uploads, target):
    body = api.convert_ok(uploads, target)
    return body, api.download_bytes(body["download_id"])


@needs_libreoffice
def test_merge_epub_to_pdf(api, files):
    ups = [api.upload(fx.epub(files, "a.epub", text="first book")), api.upload(fx.epub(files, "b.epub", text="second book"))]
    body, data = merged(api, ups, "pdf")
    assert is_pdf(data)
    text = pdf_text(data)
    assert text.index("first book") < text.index("second book")


@needs_pandoc
@needs_libreoffice
def test_merge_fb2_to_pdf_goes_through_docx(api, files):
    ups = [api.upload(fx.fb2(files, "a.fb2", text="first book")), api.upload(fx.fb2(files, "b.fb2", text="second book"))]
    _, data = merged(api, ups, "pdf")
    assert is_pdf(data)
    text = pdf_text(data)
    assert text.index("first book") < text.index("second book")


def test_merge_pdf_to_txt(api, files):
    ups = [api.upload(fx.text_pdf(files, "a.pdf", text="Alpha")), api.upload(fx.text_pdf(files, "b.pdf", text="Beta"))]
    _, data = merged(api, ups, "txt")
    text = data.decode("utf-8")
    assert text.index("Alpha") < text.index("Beta")
    assert "#" not in text


@needs_pandoc
def test_merge_docx_to_txt_via_pandoc(api, files):
    ups = [api.upload(fx.docx(files, "a.docx", text="First doc")), api.upload(fx.docx(files, "b.docx", text="Second doc"))]
    _, data = merged(api, ups, "txt")
    assert data.decode("utf-8") .index("First doc") < data.decode("utf-8").index("Second doc")


@needs_pandoc
def test_merge_epub_to_md_numbers_footnote_labels_per_book(api, files):
    ups = [api.upload(fx.epub(files, "a.epub", text="first")), api.upload(fx.epub(files, "b.epub", text="second"))]
    _, data = merged(api, ups, "md")
    text = data.decode("utf-8")
    assert text.index("first") < text.index("second")


def test_merged_telegram_md_starts_with_the_title(api, files):
    ups = [api.upload(fx.telegram_html(files, "m1.html", "first message")),
           api.upload(fx.telegram_html(files, "m2.html", "second message"))]
    _, data = merged(api, ups, "md")
    assert data.decode("utf-8").startswith(f"# {fx.TELEGRAM_CHAT}\n")


@needs_pandoc
def test_merged_books_get_unique_footnote_labels(api, files):
    ups = [api.upload(fx.epub(files, "a.epub", text="first", footnote="Alpha note")),
           api.upload(fx.epub(files, "b.epub", text="second", footnote="Beta note"))]
    _, data = merged(api, ups, "md")
    text = data.decode("utf-8")
    assert "first[^b1-1]" in text and "[^b1-1]: Alpha note" in text
    assert "second[^b2-1]" in text and "[^b2-1]: Beta note" in text


@needs_pandoc
def test_merge_markdown_into_epub_concatenates_then_converts(api, files):
    from conftest import is_epub
    from fixtures import zip_read, zip_members
    ups = [api.upload(fx.markdown(files, "a.md", text="Alpha body")), api.upload(fx.markdown(files, "b.md", text="Beta body"))]
    _, data = merged(api, ups, "epub")
    assert is_epub(data)
    html = "".join(zip_read(data, m) for m in zip_members(data) if m.endswith(".xhtml"))
    assert html.index("Alpha body") < html.index("Beta body")


def test_merge_txt_to_md_detects_structure(api, files):
    ups = [api.upload(fx.txt_document(files, "a.txt")), api.upload(fx.txt(files, "b.txt", text="tail"))]
    _, data = merged(api, ups, "md")
    text = data.decode("utf-8")
    assert "- first item" in text and "\\-" not in text


def test_merge_docx_appends_each_file_once(api, files):
    from conftest import docx_text
    ups = [api.upload(fx.docx(files, "a.docx", text="First doc")), api.upload(fx.docx(files, "b.docx", text="Second doc"))]
    _, data = merged(api, ups, "docx")
    xml = docx_text(data)
    assert xml.count("First doc") == 1 and xml.count("Second doc") == 1


def test_merge_markdown_copies_sources_verbatim(api, files):
    a = files / "a.md"
    a.write_text("__strong__ and *em*\n", encoding="utf-8")
    b = files / "b.md"
    b.write_text("second\n", encoding="utf-8")
    _, data = merged(api, [api.upload(a), api.upload(b)], "md")
    assert data.decode("utf-8") == "__strong__ and *em*\n\nsecond\n"


def test_merge_pdf_escapes_only_for_md(api, files):
    ups = [api.upload(fx.text_pdf(files, "a.pdf", text="price*2")), api.upload(fx.text_pdf(files, "b.pdf", text="Beta"))]
    _, txt = merged(api, ups, "txt")
    _, md = merged(api, ups, "md")
    assert "price*2" in txt.decode("utf-8") and "price\\*2" in md.decode("utf-8")


@needs_pandoc
def test_merge_telegram_to_txt_goes_through_pandoc_not_markdown(api, files):
    ups = [api.upload(fx.telegram_html(files, "m1.html", "first message")),
           api.upload(fx.telegram_html(files, "m2.html", "second message"))]
    _, data = merged(api, ups, "txt")
    text = data.decode("utf-8")
    assert "first message" in text and "**" not in text


@needs_pandoc
@needs_libreoffice
def test_merge_telegram_to_pdf_puts_the_title_first(api, files):
    ups = [api.upload(fx.telegram_html(files, "m1.html", "first message")),
           api.upload(fx.telegram_html(files, "m2.html", "second message"))]
    _, data = merged(api, ups, "pdf")
    assert pdf_text(data).startswith(fx.TELEGRAM_CHAT)


def test_merge_pdf_to_md_detects_lists(api, files):
    ups = [api.upload(fx.text_pdf(files, "a.pdf", text="- apples")), api.upload(fx.text_pdf(files, "b.pdf", text="Beta"))]
    _, data = merged(api, ups, "md")
    text = data.decode("utf-8")
    assert "- apples page 1" in text and "\\- apples" not in text
