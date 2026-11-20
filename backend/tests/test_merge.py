"""Merging several uploads (file_id is a comma-separated list)."""
from pathlib import Path

import fixtures as fx
import pytest
from conftest import (
    docx_text,
    is_docx,
    is_epub,
    is_fb2,
    is_pdf,
    needs_libreoffice,
    needs_pandoc,
    pdf_text,
)


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


def page_lines(pdf: bytes) -> list[list[tuple]]:
    """Per page: (text, font, size, colour, x0, y0) of every line LibreOffice drew."""
    import fitz
    pages = []
    for page in fitz.open(stream=pdf, filetype="pdf"):
        lines = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if spans:
                    lines.append(("".join(s["text"] for s in spans).strip(), spans[0]["font"],
                                  round(spans[0]["size"], 1), spans[0]["color"], line["bbox"][0], line["bbox"][1]))
        pages.append((round(page.rect.width), round(page.rect.height), lines))
    return pages


def looks_alike(pages, want) -> bool:
    """Same pages, lines, fonts, sizes and colours; each line within 1 pt of its place."""
    def same(a, b):
        return a[:4] == b[:4] and abs(a[4] - b[4]) <= 1 and abs(a[5] - b[5]) <= 1
    return len(pages) == len(want) and all(
        p[:2] == w[:2] and len(p[2]) == len(w[2]) and all(map(same, p[2], w[2])) for p, w in zip(pages, want))


def drawn(path) -> list:
    from app.engines import engine_libreoffice
    return page_lines(Path(engine_libreoffice(str(path), str(path.parent), "pdf")).read_bytes())


@needs_libreoffice
@pytest.mark.parametrize("order", [("report", "form", "again"), ("form", "report", "again")])
def test_merged_word_files_each_keep_their_own_look(api, files, order):
    """Page setup, fonts, sizes, alignment, line spacing, spacing, indents and
    headers of each file: its pages in the merged document are drawn as the
    file alone, though the files set all of these differently, whichever
    comes first."""
    made = {"report": fx.word_look(files, "report.docx", "report", "alpha beta gamma delta epsilon zeta"),
            "form": fx.word_look(files, "form.docx", "form", "omega psi chi phi upsilon tau"),
            "again": fx.word_look(files, "report2.docx", "report", "kappa lambda mu nu xi omicron")}
    _, data = merged(api, [api.upload(made[name]) for name in order], "docx")
    result = files / "merged.docx"
    result.write_bytes(data)
    assert looks_alike(drawn(result), [page for name in order for page in drawn(made[name])])


def test_merged_word_styles_say_what_word_reads(api, files):
    """What LibreOffice draws the same either way but Word does not: a font
    next to a theme font is overruled by the theme font, a font slot a file
    leaves open takes the merged document's default, and a table with no
    style takes the default table style of the document it is in."""
    import io

    from docx import Document
    from docx.oxml.ns import qn
    report = fx.word_look(files, "report.docx", "report", "alpha beta gamma delta epsilon zeta")
    form = fx.word_look(files, "form.docx", "form", "omega psi chi phi upsilon tau")
    _, data = merged(api, [api.upload(report), api.upload(form)], "docx")
    doc = Document(io.BytesIO(data))
    form_normal = doc.styles["Normal (2)"].element
    fonts = form_normal.find(f'{qn("w:rPr")}/{qn("w:rFonts")}')
    assert fonts.get(qn("w:ascii")) == "Arial" and fonts.get(qn("w:asciiTheme")) is None
    # the form names no East Asian font anywhere: Word's own, not the report's theme font
    assert fonts.get(qn("w:eastAsia")) == "Times New Roman"
    bare = next(t for t in doc.tables if "upsilon!" in t.cell(0, 0).text)
    style = doc.styles.element.get_by_id(bare._tbl.tblPr.find(qn("w:tblStyle")).get(qn("w:val")))
    assert style.find(f'{qn("w:tblPr")}/{qn("w:tblCellMar")}/{qn("w:left")}').get(qn("w:w")) == "400"


def test_a_merged_word_file_is_whole(api, files):
    """What Word checks on opening: every header and footer a section names
    is there and named once, no two styles share a name, one default style
    of each kind;
    and a style based on Normal of a Word in another language is based on
    the merged document's Normal, not on a second copy of it."""
    import io

    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn
    report = fx.word_look(files, "report.docx", "report", "alpha beta gamma delta epsilon zeta")
    form = fx.word_look(files, "form.docx", "form", "omega psi chi phi upsilon tau")
    local = fx.word_look(files, "local.docx", "report", "kappa lambda mu nu xi omicron", local_ids=True)
    _, data = merged(api, [api.upload(p) for p in (report, form, local)], "docx")
    doc = Document(io.BytesIO(data))
    rels = doc.part.rels
    for ref in doc.element.body.iter(qn("w:headerReference"), qn("w:footerReference")):
        rel = rels[ref.get(qn("r:id"))]
        assert rel.reltype in (RT.HEADER, RT.FOOTER), rel.reltype
    for setup in doc.element.body.iter(qn("w:sectPr")):
        kinds = [(r.tag, r.get(qn("w:type"))) for r in setup.iter(qn("w:headerReference"), qn("w:footerReference"))]
        assert len(kinds) == len(set(kinds)), kinds      # one header and one footer of each kind
    names = [s.name for s in doc.styles]
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)
    kinds = [s.get(qn("w:type")) for s in doc.styles.element.findall(qn("w:style")) if s.get(qn("w:default")) == "1"]
    assert len(kinds) == len(set(kinds))
    quote = doc.styles["Quote note"].element
    assert quote.find(qn("w:basedOn")).get(qn("w:val")) == doc.styles["Normal"].style_id
