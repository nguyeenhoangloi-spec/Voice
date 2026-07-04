"""
Media probe utility - get video/audio metadata.
Uses ffprobe if available, falls back to ffmpeg -i parsing.
"""
import subprocess
import json
import re
import logging

from app.utils.ffmpeg_utils import get_ffmpeg_path

logger = logging.getLogger(__name__)


def _probe_with_ffprobe(file_path: str) -> dict:
    """Try probing with ffprobe (may crash on some Windows conda installs)"""
    try:
        from app.utils.ffmpeg_utils import get_ffprobe_path
        ffprobe = get_ffprobe_path()
    except FileNotFoundError:
        return None

    try:
        cmd = [
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"ffprobe failed for {file_path}: {e}")
        return None


def _probe_with_ffmpeg(file_path: str) -> dict:
    """Fallback: parse ffmpeg -i stderr output for metadata"""
    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-i", file_path, "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        stderr = result.stderr

        # Parse duration
        duration = 0.0
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
        if dur_match:
            h, m, s, cs = dur_match.groups()
            duration = int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100

        # Check for video/audio streams
        has_video = bool(re.search(r"Stream\s+#\d+.*:\s*Video:", stderr))
        has_audio = bool(re.search(r"Stream\s+#\d+.*:\s*Audio:", stderr))

        # Get file size
        import os
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        return {
            "format": {
                "duration": str(duration),
                "size": str(file_size),
                "format_name": "unknown"
            },
            "streams": [
                {"codec_type": "video"} if has_video else None,
                {"codec_type": "audio"} if has_audio else None,
            ]
        }
    except Exception as e:
        logger.error(f"ffmpeg probe also failed for {file_path}: {e}")
        return None


def probe_media_file(file_path: str) -> dict:
    """
    Get media file metadata (duration, format, codecs).
    Tries ffprobe first, falls back to ffmpeg -i parsing.
    """
    # Try ffprobe first
    probe_data = _probe_with_ffprobe(file_path)

    # Fallback to ffmpeg if ffprobe failed
    if not probe_data:
        probe_data = _probe_with_ffmpeg(file_path)

    if not probe_data:
        raise Exception(f"Cannot probe media file: {file_path}")

    format_info = probe_data.get("format", {})
    duration = float(format_info.get("duration", 0.0))
    size = int(format_info.get("size", 0))

    has_audio = False
    has_video = False
    for stream in probe_data.get("streams", []):
        if stream is None:
            continue
        codec_type = stream.get("codec_type")
        if codec_type == "audio":
            has_audio = True
        elif codec_type == "video":
            has_video = True

    return {
        "success": True,
        "duration": duration,
        "file_size": size,
        "has_audio": has_audio,
        "has_video": has_video,
        "format_name": format_info.get("format_name", ""),
    }
