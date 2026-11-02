"""Shared harness for the backend characterization tests.

The tests talk to the API only through FastAPI's TestClient, the same way the
frontend does, so they keep passing while the code behind the routes moves.

The server runs in a throw-away working directory: the app keeps its files
under ``./storage`` (or ``$LOCAL_DOC_STORAGE``), so nothing leaks into the repo.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

# absolute(), not resolve(): when the tree is a symlinked overlay (mutation
# testing), the code next to these tests is the code under test.
BACKEND = Path(os.path.abspath(__file__)).parents[1]
TESTS = Path(os.path.abspath(__file__)).parent
for p in (str(BACKEND), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _missing(*binaries: str) -> list[str]:
    return [b for b in binaries if shutil.which(b) is None]


def requires(*binaries: str):
    """skipif marker for conversions that need a system program."""
    missing = _missing(*binaries)
    return pytest.mark.skipif(bool(missing), reason=f"system binary not installed: {', '.join(missing)}")


needs_pandoc = requires("pandoc")
needs_libreoffice = requires("libreoffice")
needs_tesseract = requires("tesseract")
needs_ffmpeg = requires("ffmpeg", "ffprobe")
needs_calibre = requires("ebook-convert")


@pytest.fixture(scope="session")
def server_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("server")
    return root


@pytest.fixture(scope="session")
def app(server_dir):
    os.environ["LOCAL_DOC_STORAGE"] = str(server_dir / "storage")
    previous = os.getcwd()
    os.chdir(server_dir)
    try:
        import main  # noqa: WPS433 — import after chdir: storage paths are relative to cwd
        yield main.app
    finally:
        os.chdir(previous)


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def files(tmp_path) -> Path:
    d = tmp_path / "in"
    d.mkdir()
    return d


class Api:
    """The three calls the frontend makes: upload, convert, download."""

    def __init__(self, client):
        self.client = client

    def upload(self, path: Path) -> dict:
        with open(path, "rb") as f:
            res = self.client.post("/api/upload", files={"file": (path.name, f)})
        assert res.status_code == 200, res.text
        return res.json()

    def convert(self, uploads, target: str, source_ext: str | None = None, **form):
        uploads = uploads if isinstance(uploads, list) else [uploads]
        data = {
            "file_id": ",".join(u["id"] for u in uploads),
            "source_ext": source_ext or uploads[0]["ext"],
            "target_format": target,
        }
        data.update({k: str(v) for k, v in form.items()})
        return self.client.post("/api/convert", data=data)

    def convert_ok(self, uploads, target: str, **kw) -> dict:
        res = self.convert(uploads, target, **kw)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "success"
        assert body["download_id"]
        assert isinstance(body["meta"], dict) and body["meta"]["size"] > 0
        return body

    def download(self, download_id: str, name: str | None = None):
        params = {"name": name} if name else None
        return self.client.get(f"/api/download/{download_id}", params=params)

    def download_bytes(self, download_id: str) -> bytes:
        res = self.download(download_id)
        assert res.status_code == 200, res.text
        assert res.content, "downloaded file is empty"
        return res.content

    def roundtrip(self, path: Path, target: str, **kw) -> tuple[dict, bytes]:
        body = self.convert_ok(self.upload(path), target, **kw)
        return body, self.download_bytes(body["download_id"])


@pytest.fixture
def api(client) -> Api:
    return Api(client)


# --- magic-byte checks ------------------------------------------------------

def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def is_zip_with(data: bytes, member: str) -> bool:
    from fixtures import zip_members
    return data[:2] == b"PK" and member in zip_members(data)


def is_docx(data: bytes) -> bool:
    return is_zip_with(data, "word/document.xml")


def is_pptx(data: bytes) -> bool:
    return is_zip_with(data, "ppt/presentation.xml")


def is_epub(data: bytes) -> bool:
    from fixtures import zip_read
    return is_zip_with(data, "mimetype") and zip_read(data, "mimetype").strip() == "application/epub+zip"


def is_fb2(data: bytes) -> bool:
    return b"<FictionBook" in data[:2000]


def is_mp3(data: bytes) -> bool:
    return data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)


def is_mp4(data: bytes) -> bool:
    return data[4:8] == b"ftyp"


def is_webm(data: bytes) -> bool:
    return data[:4] == b"\x1a\x45\xdf\xa3" and b"webm" in data[:64]


def codecs(data: bytes, tmp_dir) -> list[str]:
    """Codec names of every stream, as ffprobe reports them."""
    import subprocess
    path = tmp_dir / "probe.bin"
    path.write_bytes(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return sorted(out.stdout.split())


def docx_text(data: bytes) -> str:
    from fixtures import zip_read
    return zip_read(data, "word/document.xml")


def pdf_text(data: bytes) -> str:
    import fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "".join(p.get_text() for p in doc)
