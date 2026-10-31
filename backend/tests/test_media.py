"""MP4/WebM -> MP3 and WebM -> MP4 through ffmpeg."""
import fixtures as fx
from conftest import is_mp3, is_mp4, needs_ffmpeg

pytestmark = needs_ffmpeg


def test_mp4_to_mp3(api, files):
    body, data = api.roundtrip(fx.mp4(files), "mp3")
    assert body["engine"] == "ffmpeg"
    assert is_mp3(data)
    assert abs(body["meta"]["duration"] - 1.0) < 0.3


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
