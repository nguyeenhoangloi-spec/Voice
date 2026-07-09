import yt_dlp
import os
import glob
import logging
from urllib.parse import urlparse
from app.services.link_adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


def _get_ydl_base_opts() -> dict:
    """Base yt-dlp options that work around YouTube 403 errors and DPAPI decryption crash"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreconfig': True,
        'noplaylist': True,
        # Use multiple player clients to avoid 403 blocks. Android/iOS clients are more robust.
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
    }
    return opts


class YouTubeAdapter(BaseAdapter):
    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return "youtube.com" in domain or "youtu.be" in domain

    def extract_metadata(self, url: str) -> dict:
        ydl_opts = _get_ydl_base_opts()
        ydl_opts['skip_download'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    "success": True,
                    "title": info.get("title", "YouTube Video"),
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": info.get("duration", 0),
                    "source": "youtube",
                    "author": info.get("uploader", "Unknown"),
                    "description": ((info.get("description", "") or "")[:200] + "...")
                }
        except Exception as e:
            # Fallback strategy: try with Chrome cookies ONLY if standard fails and wrap to prevent crash
            try:
                opts_fallback = _get_ydl_base_opts()
                opts_fallback['skip_download'] = True
                opts_fallback['cookiesfrombrowser'] = ('chrome',)
                with yt_dlp.YoutubeDL(opts_fallback) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return {
                        "success": True,
                        "title": info.get("title", "YouTube Video"),
                        "thumbnail": info.get("thumbnail", ""),
                        "duration": info.get("duration", 0),
                        "source": "youtube",
                        "author": info.get("uploader", "Unknown"),
                        "description": ((info.get("description", "") or "")[:200] + "...")
                    }
            except Exception as fe:
                return {
                    "success": False,
                    "error": f"YouTube metadata error: {str(e)} (Fallback error: {str(fe)})"
                }

    def download(self, url: str, output_path: str) -> str:
        """
        Download video from YouTube. Tries multiple strategies to avoid 403.
        """
        base_path, _ = os.path.splitext(output_path)

        # Strategy 1: Multi-client, best quality with flexible format
        strategies = [
            {
                **_get_ydl_base_opts(),
                'outtmpl': base_path + '.%(ext)s',
                # Flexible: tries merged video+audio first, then falls back to any best single file
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            },
            {
                # Strategy 2: iOS client — often bypasses format restrictions
                'quiet': True,
                'no_warnings': True,
                'ignoreconfig': True,
                'noplaylist': True,
                'outtmpl': base_path + '.%(ext)s',
                'format': 'bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios']
                    }
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15',
                },
            },
            {
                # Strategy 3: Android client — reliable for most restricted videos
                'quiet': True,
                'no_warnings': True,
                'ignoreconfig': True,
                'noplaylist': True,
                'outtmpl': base_path + '.%(ext)s',
                'format': 'best[ext=mp4]/best',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android']
                    }
                },
            },
            {
                # Strategy 4: Try with Chrome cookies if available
                **_get_ydl_base_opts(),
                'outtmpl': base_path + '.%(ext)s',
                'format': 'bestvideo+bestaudio/best',
                'cookiesfrombrowser': ('chrome',),
            },
            {
                # Strategy 5: Audio only — always works as last resort
                'quiet': True,
                'no_warnings': True,
                'ignoreconfig': True,
                'noplaylist': True,
                'outtmpl': base_path + '.%(ext)s',
                'format': 'bestaudio/best',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios']
                    }
                },
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }],
            },
        ]

        last_error = None
        for idx, ydl_opts in enumerate(strategies):
            try:
                logger.info(f"Download strategy {idx + 1} for: {url}")

                # Clean up any partial downloads from previous attempts
                for old_file in glob.glob(base_path + ".*"):
                    if old_file != output_path:
                        try:
                            os.remove(old_file)
                        except Exception:
                            pass

                # Try to set ffmpeg location for yt-dlp
                try:
                    from app.utils.ffmpeg_utils import get_ffmpeg_path
                    ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
                    ydl_opts['ffmpeg_location'] = ffmpeg_dir
                except Exception:
                    pass

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                # Find the downloaded file
                downloaded_files = glob.glob(base_path + ".*")
                if not downloaded_files:
                    raise FileNotFoundError(f"No file produced for pattern: {base_path}.*")

                # Pick best file (prefer mp4, then any video, then audio)
                actual_file = downloaded_files[0]
                for f in downloaded_files:
                    if f.endswith('.mp4'):
                        actual_file = f
                        break
                    elif f.endswith(('.webm', '.mkv')):
                        actual_file = f

                logger.info(f"Downloaded: {actual_file} ({os.path.getsize(actual_file)} bytes)")

                # Rename to expected output path
                if actual_file != output_path:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(actual_file, output_path)

                # Verify file
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Download success: {output_path}")
                    return output_path
                else:
                    raise FileNotFoundError("Downloaded file is missing or too small")

            except Exception as e:
                last_error = e
                logger.warning(f"Strategy {idx + 1} failed: {e}")
                continue

        raise Exception(f"All download strategies failed. Last error: {last_error}")
