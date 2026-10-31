"""Exact metadata values, pinned from the original get_metadata."""
import logging

import fixtures as fx


def test_docx_counts_table_text_runs_and_pictures(api, files):
    meta = api.upload(fx.docx_rich(files))["meta"]
    # paragraphs say 2 words; all w:t runs ("Hello ", "world", "cell one", "cell two") say 6
    assert (meta["words"], meta["chars"], meta["images"], meta["pages"]) == (6, 30, 1, 1)


def test_docx_without_page_count_has_no_pages(api, files, caplog):
    meta = api.upload(fx.docx_rich(files, without_pages=True))["meta"]
    assert meta["pages"] == "N/A"


def test_docx_without_app_xml_logs_and_has_no_pages(api, files, caplog):
    import io, zipfile
    src = fx.docx(files)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            if item.filename == "docProps/app.xml":
                continue
            data = zin.read(item.filename)
            if item.filename in ("_rels/.rels", "[Content_Types].xml"):   # drop references to it
                import re
                data = re.sub(rb"<(Relationship|Override)[^>]*app\.xml[^>]*/>", b"", data)
            zout.writestr(item, data)
    src.write_bytes(out.getvalue())
    with caplog.at_level(logging.DEBUG):
        meta = api.upload(src)["meta"]
    assert meta["pages"] == "N/A" and meta["words"] == 7           # the rest is still read
    recs = [r for r in caplog.records if "get_metadata" in r.getMessage()]
    assert recs and recs[0].exc_info and recs[0].exc_info[0] is KeyError


def test_epub_counts_exactly(api, files):
    meta = api.upload(fx.epub(files))["meta"]
    assert (meta["words"], meta["chars"]) == (12, 70)


def test_pdf_with_text_over_a_picture_is_not_a_scan(api, files):
    meta = api.upload(fx.background_pdf(files))["meta"]
    assert "scanned" not in meta
    assert (meta["words"], meta["images"]) == (5, 1)


def test_docx_chars_come_from_paragraphs_when_word_counts_tie(api, files):
    from docx import Document
    path = files / "runs.docx"
    d = Document()
    p = d.add_paragraph("Hello ")
    p.add_run("world")
    d.save(str(path))
    meta = api.upload(path)["meta"]
    assert (meta["words"], meta["chars"]) == (2, 11)     # runs joined would give 12
