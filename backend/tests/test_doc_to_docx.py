"""DOC -> DOCX tool: LibreOffice opens the Word 97-2003 file and saves it as
DOCX directly, so the formatting survives (a detour through pandoc would keep
only the text and the headings)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import docx_text, is_docx, needs_libreoffice

pytestmark = needs_libreoffice

TEXT = "Звіт, Завдання №2"


def _formatted_doc(directory: Path) -> Path:
    """A real binary .doc with a bold, red, 20 pt run, made by LibreOffice."""
    import docx
    from docx.shared import Pt, RGBColor

    src = directory / "formatted_src.docx"
    document = docx.Document()
    run = document.add_paragraph().add_run(TEXT)
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    document.save(src)
    outdir = directory / "lo_doc"
    outdir.mkdir(exist_ok=True)
    subprocess.run(["libreoffice", f"-env:UserInstallation=file://{directory}/lo_profile", "--headless",
                    "--convert-to", "doc", str(src), "--outdir", str(outdir)],
                   check=True, capture_output=True, timeout=180)
    path = directory / "formatted.doc"
    shutil.move(str(outdir / "formatted_src.doc"), path)
    assert path.read_bytes()[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # OLE2: really the old format
    return path


@pytest.fixture
def formatted_doc(files) -> Path:
    return _formatted_doc(files)


def test_doc_to_docx_gives_a_docx_with_the_text(api, formatted_doc):
    _, data = api.roundtrip(formatted_doc, "docx")
    assert is_docx(data) and TEXT in docx_text(data)


def test_doc_to_docx_keeps_the_formatting(api, formatted_doc):
    _, data = api.roundtrip(formatted_doc, "docx")
    xml = docx_text(data)
    assert 'w:color w:val="FF0000"' in xml   # red
    assert 'w:sz w:val="40"' in xml          # 20 pt (half-points)
    assert "<w:b/>" in xml or '<w:b w:val="true"/>' in xml


def test_doc_to_docx_leaves_no_temporary_files(api, formatted_doc, server_dir):
    before = set((server_dir / "storage" / "outputs").iterdir())
    body = api.convert_ok(api.upload(formatted_doc), "docx")
    after = set((server_dir / "storage" / "outputs").iterdir())
    assert {p.name for p in after - before} == {body["download_id"]}
