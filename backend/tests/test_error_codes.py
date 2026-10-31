"""Error responses carry a machine-readable code (task 8) and English detail."""
import pytest

import fixtures as fx
from conftest import needs_ffmpeg


def code_of(res):
    body = res.json()
    assert set(body) >= {"code", "detail"}
    return body["code"]


def test_drm_azw3(api, files):
    res = api.convert(api.upload(fx.azw3_drm(files)), "epub")
    assert (res.status_code, code_of(res)) == (422, "EBOOK_DRM_PROTECTED")


def test_kfx_is_reported_as_kfx(api, files):
    kfx = files / "book.azw3"
    kfx.write_bytes(b"CONT" + b"\x00" * 200)
    res = api.convert(api.upload(kfx), "epub")
    assert (res.status_code, code_of(res)) == (422, "EBOOK_KFX")


def test_not_a_kindle_book(api, files):
    junk = files / "junk.azw3"
    junk.write_bytes(b"\x00" * 200)
    res = api.convert(api.upload(junk), "epub")
    assert (res.status_code, code_of(res)) == (422, "EBOOK_INVALID")


def test_azw3_to_unsupported_target(api, files):
    res = api.convert(api.upload(fx.azw3_renamed_epub(files)), "txt")
    assert (res.status_code, code_of(res)) == (422, "UNSUPPORTED_CONVERSION")


@pytest.mark.parametrize("target", ["mp3", "mp4"])
def test_media_target_from_a_document(api, files, target):
    res = api.convert(api.upload(fx.docx(files)), target)
    assert (res.status_code, code_of(res)) == (422, "UNSUPPORTED_CONVERSION")


@needs_ffmpeg
def test_video_without_audio(api, files):
    res = api.convert(api.upload(fx.webm(files, "s.webm", audio=False)), "mp3")
    assert (res.status_code, code_of(res)) == (422, "MEDIA_NO_AUDIO")


@needs_ffmpeg
def test_webm_without_video(api, files):
    res = api.convert(api.upload(fx.webm(files, "a.webm", video=False)), "mp4")
    assert (res.status_code, code_of(res)) == (422, "MEDIA_NO_VIDEO")


def test_missing_ffmpeg_is_dependency_missing(api, files, monkeypatch):
    up = api.upload(fx.text_pdf(files, "fake.mp4"))
    import app.media
    monkeypatch.setattr(app.media.shutil, "which", lambda name: None)
    res = api.convert(up, "mp3")
    assert (res.status_code, code_of(res)) == (500, "DEPENDENCY_MISSING")
    assert "MP4 to MP3" in res.json()["detail"]


def test_engine_failure_is_conversion_failed(api, files):
    res = api.convert(api.upload(fx.text_pdf(files)), "epub")
    assert (res.status_code, code_of(res)) == (500, "CONVERSION_FAILED")


def test_merge_failure_is_json_too(api, files):
    ups = [api.upload(fx.pptx(files, f"d{i}.pptx")) for i in (1, 2)]
    res = api.convert(ups, "pptx")
    assert (res.status_code, code_of(res)) == (500, "CONVERSION_FAILED")


def test_missing_form_field_is_invalid_request(client):
    res = client.post("/api/convert", data={"file_id": "x"})
    assert (res.status_code, code_of(res)) == (422, "INVALID_REQUEST")


@pytest.mark.parametrize("make,target", [(fx.azw3_drm, "epub"), (fx.docx, "mp3")])
def test_user_facing_detail_is_english(api, files, make, target):
    detail = api.convert(api.upload(make(files)), target).json()["detail"]
    assert detail.isascii(), detail
