"""POST /api/upload: stores the file and returns id, ext and metadata."""
import uuid

import fixtures as fx
from conftest import needs_ffmpeg


def test_upload_returns_uuid_ext_and_original_name(api, files):
    body = api.upload(fx.text_pdf(files, "Report.PDF"))
    uuid.UUID(body["id"])
    assert body["ext"] == "pdf"            # lower-cased
    assert body["original_name"] == "Report.PDF"


def test_pdf_metadata_counts_pages_and_words(api, files):
    meta = api.upload(fx.text_pdf(files, pages=2))["meta"]
    assert meta["pages"] == 2
    assert meta["words"] > 10
    assert meta["images"] == 0
    assert meta["size"] > 0


def test_scanned_pdf_is_flagged(api, files):
    meta = api.upload(fx.scanned_pdf(files))["meta"]
    assert meta["scanned"] is True
    assert meta["words"].startswith("N/A")
    assert meta["images"] == 1


def test_docx_metadata(api, files):
    meta = api.upload(fx.docx(files))["meta"]
    assert meta["words"] >= 5
    assert meta["pages"] == 1


def test_pptx_metadata_counts_slides(api, files):
    assert api.upload(fx.pptx(files))["meta"]["pages"] == 1


def test_text_metadata_reports_encoding(api, files):
    meta = api.upload(fx.txt(files, encoding="cp1251"))["meta"]
    assert meta["encoding"] == "cp1251"
    assert meta["words"] == 17


def test_ebook_metadata_counts_words(api, files):
    assert api.upload(fx.epub(files))["meta"]["words"] > 5
    assert api.upload(fx.fb2(files))["meta"]["words"] > 5


def test_unknown_metadata_is_na(api, files):
    meta = api.upload(fx.text_image(files))["meta"]
    assert meta["pages"] == meta["words"] == meta["chars"] == meta["images"] == "N/A"


@needs_ffmpeg
def test_media_metadata_has_duration(api, files):
    meta = api.upload(fx.mp4(files))["meta"]
    assert abs(meta["duration"] - 1.0) < 0.2


def test_html_and_markdown_metadata_report_encoding(api, files):
    for path in (fx.html(files), fx.markdown(files)):
        meta = api.upload(path)["meta"]
        assert meta["encoding"] == "utf-8"
        assert meta["words"] > 3


def test_docx_page_count_from_sections_when_app_xml_says_one(api, files):
    from docx import Document
    from docx.enum.section import WD_SECTION
    path = files / "two.docx"
    d = Document()
    d.add_paragraph("one")
    d.add_section(WD_SECTION.NEW_PAGE)
    d.add_paragraph("two")
    d.save(str(path))
    assert api.upload(path)["meta"]["pages"] == 2


@needs_ffmpeg
def test_webm_metadata_has_duration(api, files):
    assert abs(api.upload(fx.webm(files))["meta"]["duration"] - 1.0) < 0.2
