"""Audio/video conversions (MP3, MP4, WebM) through the system ffmpeg/ffprobe."""
import json
import logging
import os
import shutil
import subprocess
import uuid

from app.errors import DependencyMissing, EbookInputError, ErrorCode

logger = logging.getLogger(__name__)

# ============== MP4 / WebM -> MP3, WebM -> MP4 (ffmpeg) ==============
# Звуковая дорожка видео перекодируется в MP3 системным ffmpeg (VBR,
# -q:a 2 — около 190 кбит/с), теги переносятся в ID3v2.3: эту версию
# читают и Windows, и старые плееры. WebM -> MP4 перекодирует VP8/VP9/AV1
# в H.264 и Opus/Vorbis в AAC — такой MP4 открывается везде (Windows,
# iPhone, PowerPoint, мессенджеры). Python-зависимостей нет — ffmpeg и
# ffprobe вызываются как внешние программы, по образцу engine_libreoffice.

FFMPEG_TIMEOUT = 1800       # длинное видео перекодируется минутами
FFPROBE_TIMEOUT = 60        # ffprobe читает только заголовки — это быстро


def _stderr_tail(text, lines: int = 5) -> str:
    """Последние непустые строки stderr внешней программы — для текста ошибки."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    tail = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join(tail[-lines:])


def ffprobe_duration(path: str):
    """Длительность медиафайла в секундах (float) или None.

    Исключений не бросает: метаданные — необязательная часть загрузки,
    и сбой ffprobe (нет программы, битый файл, таймаут) не должен ее ломать.
    """
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, errors="replace", timeout=FFPROBE_TIMEOUT
        )
        if proc.returncode != 0:
            return None
        # Для некоторых контейнеров ffprobe пишет "N/A" — float() упадет,
        # и длительность просто не попадет в метаданные.
        value = float(proc.stdout.strip().splitlines()[0])
    except Exception:
        logger.debug("Suppressed error in ffprobe_duration()", exc_info=True)
        return None
    return round(value, 3) if value >= 0 else None


def _require_ffmpeg(task: str):
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise DependencyMissing(
            f"Converting {task} needs ffmpeg and ffprobe; not found on the server: "
            f"{', '.join(missing)}."
        )


def _stream_info(in_path: str, kind: str, label: str) -> dict | None:
    """Первый поток вида kind ('a' — звук, 'v' — видео): {"codec_name", "pix_fmt"}
    или None, если таких потоков нет."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{kind}:0",
         "-show_entries", "stream=codec_name,pix_fmt", "-of", "json", in_path],
        capture_output=True, text=True, errors="replace", timeout=FFPROBE_TIMEOUT
    )
    if probe.returncode != 0:
        # Not a media file at all (a TypeScript .ts, a renamed document):
        # the upload is at fault, not the server, so 422 rather than 500.
        raise EbookInputError(ErrorCode.UNSUPPORTED_FORMAT,
                              f"The file is not a readable {label} file: {_stderr_tail(probe.stderr)}")
    streams = json.loads(probe.stdout or "{}").get("streams") or []
    return streams[0] if streams else None


def _run_ffmpeg(args, out_path: str, out_ext: str, fail_msg: str):
    """Запуск ffmpeg с записью во временный файл.

    При сбое или таймауте недописанный файл не должен остаться под именем
    готового результата. Расширение в конце временного имени обязательно —
    по нему ffmpeg выбирает формат на выходе.
    """
    tmp = f"{out_path}.{uuid.uuid4().hex}.tmp.{out_ext}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           *args, tmp]
    try:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                           errors="replace", timeout=FFMPEG_TIMEOUT)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"{fail_msg}: {_stderr_tail(e.stderr)}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"ffmpeg did not finish the conversion within {FFMPEG_TIMEOUT} s: "
                f"{_stderr_tail(e.stderr)}") from e
        # Как и у LibreOffice, нулевой код возврата еще не значит, что файл есть.
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError(
                f"ffmpeg finished without an error, but the {out_ext.upper()} file is empty.")
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def video_to_mp3(in_path, out_path, label: str = "MP4"):
    """MP4/WebM/M4A -> MP3: первая звуковая дорожка, видео (если есть) отбрасывается."""
    _require_ffmpeg(f"{label} to MP3")
    # Видео без звука проверяем заранее: иначе ffmpeg падает на -map 0:a:0
    # с невнятным "Stream map '0:a:0' matches no streams".
    if not _stream_info(in_path, "a", label):
        raise EbookInputError(ErrorCode.MEDIA_NO_AUDIO, "The video has no audio track.")
    _run_ffmpeg(
        ["-i", in_path, "-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2",
         "-map_metadata", "0", "-id3v2_version", "3"],
        out_path, "mp3", f"ffmpeg could not extract the audio from {label}",
    )


def mp4_to_mp3(in_path, out_path):
    """Прежнее имя — оставлено для совместимости."""
    video_to_mp3(in_path, out_path, "MP4")


def _ffmpeg_has_encoder(name: str) -> bool:
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True, errors="replace",
                              timeout=FFPROBE_TIMEOUT)
    except Exception:
        logger.debug("Suppressed error in _ffmpeg_has_encoder()", exc_info=True)
        return False
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines())


def _require_video(in_path, label: str, target: str) -> dict:
    """The first video stream's info; MEDIA_NO_VIDEO for an audio-only file."""
    _require_ffmpeg(f"{label} to {target}")
    video = _stream_info(in_path, "v", label)
    if not video:
        raise EbookInputError(ErrorCode.MEDIA_NO_VIDEO,
                              f"The {label} file has no video stream (audio only); use {label} to MP3.")
    return video


def mp4_codec_args(video: dict, audio: dict | None, has_x264: bool) -> list[str]:
    """Copy what every player opens inside MP4, re-encode the rest.

    8-bit 4:2:0 H.264 and AAC (most IPTV and modern TV recordings in TS) are
    moved into MP4 untouched: the time is disk speed, not encoding, and
    nothing is lost. MPEG-2, HEVC, VP8/VP9, 10-bit or 4:2:2 H.264 are
    re-encoded, because not every device plays them; so is MP2/AC-3/Vorbis
    sound. A pure function, so the rule is tested without ffmpeg.
    """
    if video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p":
        v = ["-c:v", "copy"]
    elif has_x264:
        # CRF 23 — стандартное качество x264; veryfast заметно быстрее
        # medium при почти том же качестве. Профиль high + yuv420p читают
        # все устройства, включая iPhone и Windows.
        v = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high"]
    else:
        # Сборка ffmpeg без libx264: MPEG-4 Part 2 тоже открывается почти везде.
        v = ["-c:v", "mpeg4", "-q:v", "3"]
    if v[1] != "copy":
        # yuv420p и четные размеры обязательны для H.264: VP9 из браузера
        # бывает yuv444/с альфа-каналом и с нечетной шириной (запись экрана).
        v += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"]
    a = ["-c:a", "copy"] if audio and audio.get("codec_name") == "aac" else ["-c:a", "aac", "-b:a", "192k"]
    return v + a


def video_to_mp4(in_path, out_path, label: str = "WebM"):
    """WebM/TS -> MP4 (H.264 + AAC), copying the streams that are already
    H.264/AAC (see mp4_codec_args)."""
    video = _require_video(in_path, label, "MP4")
    audio = _stream_info(in_path, "a", label)
    _run_ffmpeg(
        ["-i", in_path,
         "-map", "0:v:0", "-map", "0:a:0?",          # звук — если он есть
         *mp4_codec_args(video, audio, _ffmpeg_has_encoder("libx264")),
         "-map_metadata", "0",
         # moov в начале файла: видео начинает играть до полной загрузки.
         "-movflags", "+faststart"],
        out_path, "mp4", f"ffmpeg could not convert {label} to MP4",
    )


def video_to_webm(in_path, out_path, label: str = "TS"):
    """Video -> WebM: VP9 + Opus, or VP8 + Vorbis on an ffmpeg without them.

    WebM plays in every current browser and in HTML5 <video> without
    plugins; VP9/Opus is today's pairing, VP8/Vorbis the original one.
    """
    _require_video(in_path, label, "WebM")
    if _ffmpeg_has_encoder("libvpx-vp9") and _ffmpeg_has_encoder("libopus"):
        # CRF 32 with -b:v 0 is constant-quality VP9; -deadline good with
        # -cpu-used 4 and row threading keeps a long recording fast enough.
        codecs = ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-deadline", "good",
                  "-cpu-used", "4", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k"]
    else:
        codecs = ["-c:v", "libvpx", "-crf", "10", "-b:v", "2M", "-c:a", "libvorbis", "-q:a", "5"]
    _run_ffmpeg(
        ["-i", in_path,
         "-map", "0:v:0", "-map", "0:a:0?",          # звук — если он есть
         *codecs,
         "-vf", "format=yuv420p",
         "-map_metadata", "0"],
        out_path, "webm", f"ffmpeg could not re-encode {label} to WebM",
    )
