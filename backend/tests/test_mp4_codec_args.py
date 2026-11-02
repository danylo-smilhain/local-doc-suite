"""The copy-or-re-encode rule for MP4 output, without ffmpeg (app.media.mp4_codec_args)."""
import pytest

from app.media import mp4_codec_args

H264 = {"codec_name": "h264", "pix_fmt": "yuv420p"}
AAC = {"codec_name": "aac"}


def video_codec(args):
    return args[args.index("-c:v") + 1]


def audio_codec(args):
    return args[args.index("-c:a") + 1]


def test_h264_and_aac_are_copied_and_not_filtered():
    args = mp4_codec_args(H264, AAC, has_x264=True)
    assert (video_codec(args), audio_codec(args)) == ("copy", "copy")
    assert "-vf" not in args  # ffmpeg refuses a filter on a copied stream


@pytest.mark.parametrize("video", [
    {"codec_name": "h264", "pix_fmt": "yuv420p10le"},   # 10-bit
    {"codec_name": "h264", "pix_fmt": "yuv422p"},       # 4:2:2
    {"codec_name": "hevc", "pix_fmt": "yuv420p"},
    {"codec_name": "mpeg2video", "pix_fmt": "yuv420p"},
    {"codec_name": "vp9", "pix_fmt": "yuv420p"},
])
def test_other_video_is_re_encoded_to_8_bit_h264(video):
    args = mp4_codec_args(video, AAC, has_x264=True)
    assert video_codec(args) == "libx264"
    assert "format=yuv420p" in args[args.index("-vf") + 1]


@pytest.mark.parametrize("audio", [{"codec_name": "ac3"}, {"codec_name": "mp2"}, {"codec_name": "opus"}, None])
def test_other_or_missing_sound_is_encoded_as_aac(audio):
    assert audio_codec(mp4_codec_args(H264, audio, has_x264=True)) == "aac"


def test_without_libx264_falls_back_to_mpeg4():
    args = mp4_codec_args({"codec_name": "mpeg2video", "pix_fmt": "yuv420p"}, AAC, has_x264=False)
    assert video_codec(args) == "mpeg4"
