"""
FFmpeg path resolution utility.
Finds ffmpeg/ffprobe from multiple sources:
1. imageio-ffmpeg (pip package with bundled binary)
2. System PATH
3. Conda environment Library/bin
"""
import os
import sys
import shutil
import logging
import subprocess

logger = logging.getLogger(__name__)

_ffmpeg_path = None
_ffprobe_path = None


def _test_binary(path: str) -> bool:
    """Test if a binary actually works (doesn't crash)"""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _find_in_conda_env(binary_name: str) -> str:
    """Search for binary in conda environment Library/bin directory"""
    python_dir = os.path.dirname(sys.executable)
    candidate_dirs = [
        os.path.join(python_dir, "Library", "bin"),
        os.path.join(python_dir, "..", "Library", "bin"),
        os.path.join(python_dir, "Scripts"),
    ]
    for candidate_dir in candidate_dirs:
        candidate = os.path.join(candidate_dir, binary_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def get_ffmpeg_path() -> str:
    """Get the absolute path to a WORKING ffmpeg executable"""
    global _ffmpeg_path
    if _ffmpeg_path and os.path.isfile(_ffmpeg_path):
        return _ffmpeg_path

    # 1. Try imageio-ffmpeg (most reliable on Windows)
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path) and _test_binary(path):
            _ffmpeg_path = path
            logger.info(f"FFmpeg from imageio-ffmpeg: {path}")
            return _ffmpeg_path
    except ImportError:
        pass

    # 2. Check system PATH
    system_path = shutil.which("ffmpeg")
    if system_path and _test_binary(system_path):
        _ffmpeg_path = system_path
        return _ffmpeg_path

    # 3. Check conda environment
    conda_path = _find_in_conda_env("ffmpeg.exe")
    if conda_path and _test_binary(conda_path):
        _ffmpeg_path = conda_path
        return _ffmpeg_path

    # 4. Conda path without test (last resort)
    if conda_path and os.path.isfile(conda_path):
        _ffmpeg_path = conda_path
        logger.warning(f"Using untested ffmpeg: {conda_path}")
        return _ffmpeg_path

    raise FileNotFoundError(
        "ffmpeg not found. Install via: pip install imageio-ffmpeg"
    )


def get_ffprobe_path() -> str:
    """Get the absolute path to a WORKING ffprobe executable"""
    global _ffprobe_path
    if _ffprobe_path and os.path.isfile(_ffprobe_path):
        return _ffprobe_path

    # 1. Try to derive from imageio-ffmpeg's ffmpeg path
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path:
            ffprobe_candidate = ffmpeg_path.replace("ffmpeg", "ffprobe")
            if os.path.isfile(ffprobe_candidate) and _test_binary(ffprobe_candidate):
                _ffprobe_path = ffprobe_candidate
                return _ffprobe_path
            # imageio-ffmpeg may not include ffprobe, try same directory
            ffprobe_dir = os.path.dirname(ffmpeg_path)
            for name in ["ffprobe.exe", "ffprobe"]:
                candidate = os.path.join(ffprobe_dir, name)
                if os.path.isfile(candidate) and _test_binary(candidate):
                    _ffprobe_path = candidate
                    return _ffprobe_path
    except ImportError:
        pass

    # 2. Check system PATH
    system_path = shutil.which("ffprobe")
    if system_path and _test_binary(system_path):
        _ffprobe_path = system_path
        return _ffprobe_path

    # 3. Check conda environment
    conda_path = _find_in_conda_env("ffprobe.exe")
    if conda_path and _test_binary(conda_path):
        _ffprobe_path = conda_path
        return _ffprobe_path

    # 4. Conda path without test (last resort)
    if conda_path and os.path.isfile(conda_path):
        _ffprobe_path = conda_path
        logger.warning(f"Using untested ffprobe: {conda_path}")
        return _ffprobe_path

    # 5. Use ffmpeg as fallback for probing (ffmpeg can do what ffprobe does)
    logger.warning("ffprobe not found, will use ffmpeg fallback for probing")
    raise FileNotFoundError(
        "ffprobe not found. Install via: pip install imageio-ffmpeg"
    )


def get_video_duration(video_path: str) -> float:
    """Get video duration using ffmpeg (works even without ffprobe)"""
    try:
        ffprobe = get_ffprobe_path()
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, Exception):
        pass

    # Fallback: use ffmpeg to get duration
    try:
        ffmpeg = get_ffmpeg_path()
        cmd = [ffmpeg, "-i", video_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        # Parse duration from ffmpeg stderr output
        import re
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100
    except Exception:
        pass

    return 0.0


def inject_ffmpeg_to_path():
    """Automatically adds working ffmpeg/ffprobe to PATH and removes broken conda ffmpeg paths from session PATH"""
    try:
        ffmpeg_path = get_ffmpeg_path()
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        
        # Clean current PATH of broken ffmpeg directories
        path_list = os.environ.get("PATH", "").split(os.pathsep)
        cleaned_paths = []
        for p in path_list:
            if not p:
                continue
            # Check if this directory contains a broken ffmpeg (but is NOT our resolved imageio-ffmpeg folder)
            has_ffmpeg = os.path.isfile(os.path.join(p, "ffmpeg.exe")) or os.path.isfile(os.path.join(p, "ffmpeg.EXE"))
            if has_ffmpeg and os.path.normpath(p) != os.path.normpath(ffmpeg_dir):
                logger.info(f"Removing path with broken ffmpeg from session PATH: {p}")
                continue
            cleaned_paths.append(p)
            
        # Reconstruct PATH with working ffmpeg directory at the VERY BEGINNING
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.pathsep.join(cleaned_paths)
        logger.info(f"Successfully injected working FFmpeg to session PATH: {ffmpeg_dir}")
        
    except Exception as e:
        logger.warning(f"Failed to inject FFmpeg/FFprobe to PATH: {e}")


# Pre-resolve on import and inject PATH
try:
    _ffmpeg_path = get_ffmpeg_path()
    logger.info(f"FFmpeg resolved: {_ffmpeg_path}")
    inject_ffmpeg_to_path()
except FileNotFoundError:
    logger.warning("FFmpeg not found at import time")

try:
    _ffprobe_path = get_ffprobe_path()
    logger.info(f"FFprobe resolved: {_ffprobe_path}")
except FileNotFoundError:
    logger.warning("FFprobe not found at import time")

