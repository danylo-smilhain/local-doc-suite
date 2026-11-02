"""MP4/WebM -> MP3 and WebM -> MP4 through ffmpeg."""
import fixtures as fx
from conftest import codecs, is_mp3, is_mp4, is_webm, needs_ffmpeg

pytestmark = needs_ffmpeg


def test_mp4_to_mp3(api, files):
    body, data = api.roundtrip(fx.mp4(files), "mp3")
    assert body["engine"] == "ffmpeg"
    assert is_mp3(data)
    assert abs(body["meta"]["duration"] - 1.0) < 0.3


def test_m4a_to_mp3(api, files):
    body, data = api.roundtrip(fx.m4a(files), "mp3")
    assert body["engine"] == "ffmpeg"
    assert is_mp3(data)
    assert abs(body["meta"]["duration"] - 1.0) < 0.3


def test_m4a_metadata_has_duration(api, files):
    meta = api.upload(fx.m4a(files))["meta"]
    assert abs(meta["duration"] - 1.0) < 0.2


def test_webm_to_mp3(api, files):
    body, data = api.roundtrip(fx.webm(files), "mp3")
    assert body["engine"] == "ffmpeg"
    assert is_mp3(data)


def test_webm_to_mp4(api, files):
    body, data = api.roundtrip(fx.webm(files), "mp4")
    assert body["engine"] == "ffmpeg"
    assert is_mp4(data)


def test_video_without_audio_to_mp3_is_422(api, files):
    res = api.convert(api.upload(fx.webm(files, "silent.webm", audio=False)), "mp3")
    assert res.status_code == 422


def test_audio_only_webm_to_mp4_is_422(api, files):
    res = api.convert(api.upload(fx.webm(files, "audio.webm", video=False)), "mp4")
    assert res.status_code == 422


def test_non_video_to_mp3_is_422(api, files):
    res = api.convert(api.upload(fx.docx(files)), "mp3")
    assert res.status_code == 422


def test_ts_to_mp3(api, files):
    body, data = api.roundtrip(fx.ts(files), "mp3")
    assert body["engine"] == "ffmpeg"
    assert is_mp3(data)
    assert abs(body["meta"]["duration"] - 1.0) < 0.3


def test_ts_to_mp4_plays_everywhere(api, files):
    body, data = api.roundtrip(fx.ts(files), "mp4")
    assert body["engine"] == "ffmpeg"
    assert is_mp4(data)
    assert codecs(data, files) == ["aac", "h264"]


def test_ts_to_webm(api, files):
    body, data = api.roundtrip(fx.ts(files), "webm")
    assert body["engine"] == "ffmpeg"
    assert is_webm(data)
    assert codecs(data, files) == ["opus", "vp9"]
    assert abs(body["meta"]["duration"] - 1.0) < 0.3


def test_ts_metadata_has_duration(api, files):
    meta = api.upload(fx.ts(files))["meta"]
    assert abs(meta["duration"] - 1.0) < 0.2


def test_audio_only_ts_to_video_is_422(api, files):
    up = api.upload(fx.ts(files, "radio.ts", video=False))
    for target in ("mp4", "webm"):
        res = api.convert(up, target)
        assert (res.status_code, res.json()["code"]) == (422, "MEDIA_NO_VIDEO")


def test_typescript_source_named_ts_is_422_not_500(api, files):
    code = files / "app.ts"
    code.write_text("const answer: number = 42;\nexport default answer;\n")
    res = api.convert(api.upload(code), "mp4")
    assert (res.status_code, res.json()["code"]) == (422, "UNSUPPORTED_FORMAT")


def test_other_formats_to_webm_is_422(api, files):
    res = api.convert(api.upload(fx.docx(files)), "webm")
    assert (res.status_code, res.json()["code"]) == (422, "UNSUPPORTED_CONVERSION")


def test_ts_to_webm_without_vp9_falls_back_to_vp8(api, files, monkeypatch):
    import app.media
    real = app.media._ffmpeg_has_encoder
    monkeypatch.setattr(app.media, "_ffmpeg_has_encoder", lambda name: name not in ("libvpx-vp9", "libopus") and real(name))
    _, data = api.roundtrip(fx.ts(files), "webm")
    assert is_webm(data)
    assert codecs(data, files) == ["vorbis", "vp8"]
