"""The conversion registries pick the same branch as the original
``convert_document`` elif chains (transcribed condition by condition below)
for every source x target pair. A deliberate routing change must update the
oracle here too."""
import pytest

from app.models import SourceExt, TargetFormat  # no storage side effects

LO = {"docx","doc","odt","rtf","pptx","ppt","odp","xlsx","xls","ods","html","htm"}

IMAGES = ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp", "raw", "dng")


def old_single(s, t, o, tg):
    # added after the refactor: images are OCRed (they used to fall through to pandoc)
    if s in IMAGES and o in ("txt", "md"):
        return "image_text"
    # added after the refactor: DOC -> DOCX goes straight through LibreOffice
    # (it used to fall through to pandoc, which cannot read .doc)
    if s == "doc" and o == "docx":
        return "doc_docx"
    if s == "pdf":
        if t in ("docx-ocr", "docx"): return "pdf_docx"
        if t in ("txt", "md"): return "pdf_text"
        return "pandoc"
    if s == "txt": return "txt_md" if o == "md" else "txt_via_md"
    # added after the refactor: MOBI reads like AZW3; only MOBI -> AZW3 (Calibre)
    # makes an AZW3, every other source -> AZW3 is refused instead of hitting pandoc
    if s == "mobi" and o == "azw3": return "kindle_azw3"
    if s in ("azw3", "mobi"): return {"epub": "azw3_epub", "pdf": "azw3_pdf", "md": "azw3_md"}.get(o, "azw3_unsupported")
    if s == "epub" and o == "pdf": return "epub_pdf"
    if s == "fb2" and o == "pdf": return "fb2_pdf"
    if s in ("epub", "fb2") and o == "md": return "book_md"
    if s in ("html", "htm") and o == "md": return "html_md"
    if s in ("html", "htm") and o == "pdf" and tg: return "telegram_pdf"
    if o == "pdf" and s in LO: return "office_pdf"
    if s in ("mp4", "webm") and o == "mp3": return "video_mp3"
    if s == "webm" and o == "mp4": return "webm_mp4"
    if o == "azw3": return "azw3_target_unsupported"
    if o == "mp3": return "mp3_unsupported"
    if o == "mp4": return "mp4_unsupported"
    return "pandoc"

def old_merge(s, o):
    if o == "pdf": return "pdf_merger" if s == "pdf" else "merge_to_pdf"
    if o == "docx": return "merge_docx"
    if s == "txt" and o == "md": return "txt_md_merge"
    if s == "epub" and o == "epub": return "books"
    if s == "fb2" and o == "fb2": return "books"
    if o in ("txt", "md", "html"): return "text"
    return "concat"




@pytest.fixture(scope="module")
def c(app):
    """app.convert, imported only after the harness has set up storage."""
    from app import convert
    return convert


@pytest.fixture(scope="module")
def NEW(c):
    return {c.pdf_to_docx: "pdf_docx", c.pdf_to_text: "pdf_text", c.pandoc_default: "pandoc",
           c.txt_to_md: "txt_md", c.txt_via_md: "txt_via_md", c.azw3_to_epub: "azw3_epub",
           c.azw3_to_pdf: "azw3_pdf", c.azw3_to_md: "azw3_md", c.azw3_unsupported: "azw3_unsupported",
           c.epub_pdf: "epub_pdf", c.fb2_to_pdf: "fb2_pdf", c.book_to_md: "book_md", c.html_to_md: "html_md",
           c.office_to_pdf: "office_pdf", c.video_mp3: "video_mp3", c.webm_mp4: "webm_mp4",
           c.mp3_unsupported: "mp3_unsupported", c.mp4_unsupported: "mp4_unsupported",
           c.merge_pdfs: "pdf_merger", c.merge_into_pdf: "merge_to_pdf", c.merge_into_docx: "merge_docx",
           c.merge_txt_to_md: "txt_md_merge", c.merge_books: "books", c.merge_as_text: "text",
           c.merge_concat_then_pandoc: "concat",
            c.image_to_text: "image_text", c.doc_to_docx: "doc_docx",
            c.kindle_to_azw3: "kindle_azw3", c.azw3_target_unsupported: "azw3_target_unsupported"}


PAIRS = [(s.value, t) for s in SourceExt for t in TargetFormat]


@pytest.mark.parametrize("telegram", [False, True])
@pytest.mark.parametrize("source,target", PAIRS, ids=[f"{s}-{t.value}" for s, t in PAIRS])
def test_single_routing_matches_original_chain(c, NEW, source, target, telegram):
    h = c.resolve(c.SINGLE, source, target.out_ext, c.pandoc_default)
    new = NEW.get(h) if h is not c.html_to_pdf else ("telegram_pdf" if telegram else "office_pdf")
    assert new == old_single(source, target.value, target.out_ext, telegram)


@pytest.mark.parametrize("source,target", PAIRS, ids=[f"{s}-{t.value}" for s, t in PAIRS])
def test_merge_routing_matches_original_chain(c, NEW, source, target):
    h = c.resolve(c.MERGE, source, target.out_ext, c.merge_concat_then_pandoc)
    assert NEW[h] == old_merge(source, target.out_ext)
