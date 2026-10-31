"""Input validation at the API boundary (task 4): every bad input is a 4xx,
never a 500 and never a file outside storage/."""
import uuid

import pytest

import fixtures as fx

GOOD_ID = "00000000-0000-4000-8000-000000000000"


def is_client_error(res) -> bool:
    return 400 <= res.status_code < 500


def error_code(res) -> str:
    return res.json()["code"]


# --- upload ------------------------------------------------------------------

@pytest.mark.parametrize("filename", ["evil.exe", "script.sh", "noext", "archive.tar.gz", "a.txt/../../x"])
def test_upload_rejects_unlisted_extension(client, filename):
    res = client.post("/api/upload", files={"file": (filename, b"data")})
    assert res.status_code == 400
    assert error_code(res) == "UNSUPPORTED_FORMAT"


def test_upload_filename_cannot_escape_storage(client, server_dir):
    res = client.post("/api/upload", files={"file": ("../../../escape.txt", b"hello")})
    assert res.status_code == 200
    assert not (server_dir / "escape.txt").exists()
    assert not (server_dir.parent / "escape.txt").exists()
    uuid.UUID(res.json()["id"])


@pytest.mark.parametrize("filename", ["Звіт.PDF", "photo.JPG", "page.htm"])
def test_upload_accepts_listed_extensions_case_insensitively(client, filename):
    res = client.post("/api/upload", files={"file": (filename, b"data")})
    assert res.status_code == 200
    assert res.json()["ext"] == filename.rsplit(".", 1)[1].lower()


# --- convert -----------------------------------------------------------------

def convert(client, file_id=GOOD_ID, source_ext="pdf", target_format="txt"):
    return client.post("/api/convert", data={
        "file_id": file_id, "source_ext": source_ext, "target_format": target_format})


@pytest.mark.parametrize("file_id", [
    "../../etc/passwd",
    "/etc/passwd",
    "not-a-uuid",
    f"{GOOD_ID}/../../x",
    f"{GOOD_ID},../secret",
    "",
    ",",
])
def test_convert_rejects_bad_file_id(client, file_id):
    res = convert(client, file_id=file_id)
    assert is_client_error(res)
    if res.status_code == 400:
        assert error_code(res) == "INVALID_FILE_ID"


@pytest.mark.parametrize("source_ext", ["exe", "pdf/../../x", "../pdf", "", "PDF "])
def test_convert_rejects_bad_source_ext(client, source_ext):
    res = convert(client, source_ext=source_ext)
    assert is_client_error(res)
    if res.status_code == 400:
        assert error_code(res) == "UNSUPPORTED_FORMAT"


@pytest.mark.parametrize("target", ["exe", "../txt", "docx/../../x", "latex"])
def test_convert_rejects_bad_target_format(client, target):
    res = convert(client, target_format=target)
    assert res.status_code == 400
    assert error_code(res) == "UNSUPPORTED_FORMAT"


def test_convert_missing_upload_is_404_with_code(client):
    res = convert(client)
    assert res.status_code == 404
    assert error_code(res) == "FILE_NOT_FOUND"


def test_merge_with_missing_part_is_404(api, client, files):
    real = api.upload(fx.text_pdf(files))
    res = client.post("/api/convert", data={
        "file_id": f"{real['id']},{GOOD_ID}", "source_ext": "pdf", "target_format": "pdf"})
    assert res.status_code == 404
    assert error_code(res) == "FILE_NOT_FOUND"


def test_source_ext_must_match_the_upload(api, files):
    up = api.upload(fx.text_pdf(files))
    res = api.convert(up, "txt", source_ext="txt")       # file was stored as .pdf
    assert res.status_code == 404


# --- download ----------------------------------------------------------------

@pytest.mark.parametrize("download_id", [
    "..%2fmain.py",
    "..%2F..%2Fetc%2Fpasswd",
    "%2fetc%2fpasswd",
    "..",
    "main.py",
    "converted_not-a-uuid.txt",
    f"converted_{GOOD_ID}.txt",           # well-formed but does not exist
])
def test_download_rejects_bad_or_unknown_id(client, download_id):
    res = client.get(f"/api/download/{download_id}")
    assert is_client_error(res)


def test_download_never_serves_files_outside_outputs(client, server_dir):
    (server_dir / "storage" / "uploads").mkdir(parents=True, exist_ok=True)
    secret = server_dir / "storage" / "secret.txt"
    secret.write_text("top secret")
    for attempt in ("..%2fsecret.txt", "..%2F..%2Fstorage%2Fsecret.txt"):
        res = client.get(f"/api/download/{attempt}")
        assert is_client_error(res)
        assert b"top secret" not in res.content


@pytest.mark.parametrize("name,expected", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\boot.ini", "boot.ini"),
    ('a"b\r\nSet-Cookie: x.txt', "a_b__Set-Cookie_ x.txt"),
    ("Звіт 2024 (final).txt", "Звіт 2024 (final).txt"),
])
def test_download_name_is_sanitized(api, files, name, expected):
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "txt")
    res = api.download(body["download_id"], name=name)
    assert res.status_code == 200
    from urllib.parse import quote, unquote
    disposition = res.headers["content-disposition"]
    served = unquote(disposition.split("filename", 1)[1])
    assert "/" not in served and "\\" not in served and ".." not in served
    assert "\r" not in disposition and "\n" not in disposition
    assert quote(expected) in disposition or f'"{expected}"' in disposition


def test_download_name_that_sanitizes_to_nothing_uses_default(api, files):
    body = api.convert_ok(api.upload(fx.text_pdf(files)), "txt")
    res = api.download(body["download_id"], name="../..")
    assert f"LocalSuite_{body['download_id']}" in res.headers["content-disposition"]
