import os
import re
import glob
import logging
import yt_dlp
import contextlib
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from app.services.link_adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


def _extract_youtube_id(url: str) -> str:
    """Trích xuất ID của video YouTube từ URL."""
    pattern = r"(?:v=|\/embed\/|\/1080p\/|\/vi\/|youtu\.be\/|\/v\/|\/e\/|watch\?v%3D|watch\?feature=player_embedded&v=|\/shorts\/|%2Fvideos%2F)([^#\&\?]*)"
    match = re.search(pattern, url)
    if match:
        val = match.group(1)
        if len(val) == 11:
            return val
    return ""


def _get_ytdlp_base_opts() -> dict:
    """Base options for yt-dlp: quiet, no playlist, challenge solver config,
    parallel fragment downloads and auto-retry on transient network errors."""
    import shutil
    import os

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreconfig": True,
        "remote_components": ["ejs:github"],
        # Download up to 4 DASH/HLS fragments simultaneously.
        # Safe default: not aggressive enough to trigger IP-rate-limiting.
        "concurrent_fragment_downloads": 4,
        # Retry the whole request and individual fragments on transient failures.
        "retries": 5,
        "fragment_retries": 5,
    }

    # Try to find Node.js runtime to solve YouTube signature/cipher challenge (EJS)
    node_path = shutil.which("node")
    if not node_path:
        # Fallback common paths on Windows
        for p in [r"D:\nodejs\node.exe", r"C:\Program Files\nodejs\node.exe"]:
            if os.path.exists(p):
                node_path = p
                break

    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}

    return opts



# Direct media file extensions — let DirectMediaAdapter handle
_MEDIA_EXTENSIONS = {".mp4", ".webm", ".mp3", ".wav", ".ogg", ".aac", ".m4a", ".mkv", ".avi"}


@contextlib.contextmanager
def _temp_cookie_file(cookie_content: str):
    """Context manager to create a temporary cookie file and automatically delete it on exit."""
    if not cookie_content or not cookie_content.strip():
        yield None
        return

    # Ensure storage/temp folder exists
    temp_dir = Path("storage/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Write cookies to a temporary file
    tf = tempfile.NamedTemporaryFile(
        mode="w", 
        dir=str(temp_dir), 
        suffix="_cookies.txt", 
        delete=False, 
        encoding="utf-8"
    )
    try:
        tf.write(cookie_content.strip())
        tf.close()
        logger.info(f"[YTDLPAdapter] Temporary cookie file created: {tf.name}")
        yield tf.name
    finally:
        if os.path.exists(tf.name):
            try:
                os.remove(tf.name)
                logger.info(f"[YTDLPAdapter] Temporary cookie file deleted: {tf.name}")
            except Exception as e:
                logger.warning(f"[YTDLPAdapter] Failed to delete temporary cookie file: {e}")


class YTDLPAdapter(BaseAdapter):
    """
    Universal adapter powered by yt-dlp.
    Handles YouTube AND 1000+ other platforms.
    YouTube URLs receive extra mobile-client fallback strategies.
    Supports dynamic download quality and cookie authentication.
    """

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in _MEDIA_EXTENSIONS):
            return False
        return True

    def extract_metadata(self, url: str, **kwargs) -> dict:
        cookie_content = kwargs.get("cookie_content") or None

        with _temp_cookie_file(cookie_content) as cookie_file:
            meta_strategies = []
            
            if cookie_file:
                # Nếu có cookie người dùng dán, ưu tiên dùng cookie đó, sau đó fallback không dùng cookie
                meta_strategies.append({"cookiefile": cookie_file})
                meta_strategies.append({})
            else:
                # Nếu không có cookie, thử không dùng cookie trước để tránh lỗi quét Chrome/Edge
                meta_strategies.append({})
                meta_strategies.append({"cookiesfrombrowser": ("edge",)})
                meta_strategies.append({"cookiesfrombrowser": ("chrome",)})

            last_err = None
            for strategy in meta_strategies:
                try:
                    # Make sure not to reuse deleted cookiefile reference if strategy changes
                    opts = {**_get_ytdlp_base_opts(), "skip_download": True, **strategy}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        thumbnail = info.get("thumbnail", "")
                        thumbnails = info.get("thumbnails") or []
                        if thumbnails:
                            best = max(thumbnails, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), default=None)
                            if best:
                                thumbnail = best.get("url", thumbnail)
                            maxres = next((t for t in thumbnails if "maxresdefault" in (t.get("url") or "")), None)
                            if maxres:
                                thumbnail = maxres.get("url", thumbnail)
                        
                        source_name = self._detect_source(url)
                        if source_name == "youtube":
                            yt_id = _extract_youtube_id(url) or info.get("id")
                            if yt_id:
                                thumbnail = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"

                        return {
                            "success": True,
                            "title": info.get("title") or info.get("id", "Video"),
                            "thumbnail": thumbnail,
                            "duration": info.get("duration") or 0,
                            "source": source_name,
                            "author": info.get("uploader") or info.get("channel") or "Unknown",
                            "description": ((info.get("description") or "")[:200] + "..."),
                            "platform": info.get("extractor_key", "unknown"),
                            "view_count": info.get("view_count"),
                            "like_count": info.get("like_count"),
                        }
                except Exception as e:
                    last_err = e
                    logger.info(f"[YTDLPAdapter] Metadata strategy {strategy} failed: {e}")
                    if "unsupported url" in str(e).lower():
                        break
                    continue
            return {"success": False, "error": f"Khong lay duoc thong tin video: {last_err}"}

    def download(self, url: str, output_path: str, **kwargs) -> str:
        base_path, _ = os.path.splitext(output_path)
        is_youtube = "youtube.com" in url or "youtu.be" in url

        clip_start = kwargs.get("clip_start") or None
        clip_end = kwargs.get("clip_end") or None
        download_quality = kwargs.get("download_quality") or "720p"
        cookie_content = kwargs.get("cookie_content") or None
        # exact_cut=True: insert keyframe at cut point (precise, more CPU).
        # exact_cut=False: snap to nearest existing keyframe (fast, may be off by <1s).
        exact_cut = bool(kwargs.get("exact_cut", True))

        # Build partial download range options
        download_sections_opt = {}
        if clip_start or clip_end:
            start = clip_start or "00:00:00"
            end = clip_end or "99:59:59"
            download_sections_opt = {
                "download_ranges": yt_dlp.utils.download_range_func(
                    None, [(_hms_to_seconds(start), _hms_to_seconds(end))]
                ),
                "force_keyframes_at_cuts": exact_cut,
            }
            mode_label = "precise" if exact_cut else "fast (keyframe-aligned)"
            logger.info(f"[YTDLPAdapter] Partial download: {start} to {end} — cut mode: {mode_label}")

        # Map download quality to yt-dlp format selection
        height = "720"
        if download_quality == "1080p":
            height = "1080"
        elif download_quality == "480p":
            height = "480"

        # Priority: MP4+M4A (remux, no re-encode) → MP4+any audio (may re-encode audio)
        # → best height MP4 → best height any. Each slash is a fallback tier.
        FMT_STR = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}][ext=mp4]+bestaudio"
            f"/bestvideo[height<={height}]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio"
            f"/best[height<={height}][ext=mp4]/best[height<={height}]"
        )
        FMT_STR_RELAXED = f"bestvideo[height<={height}]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"

        with _temp_cookie_file(cookie_content) as cookie_file:
            strategies = []

            # 1. Custom cookies strategies (if provided)
            if cookie_file:
                strategies.append({
                    **_get_ytdlp_base_opts(), 
                    "outtmpl": base_path + ".%(ext)s", 
                    "format": FMT_STR, 
                    "cookiefile": cookie_file,
                    "merge_output_format": "mp4", 
                    **download_sections_opt
                })

            # 2. No browser cookies strategy FIRST (to prevent DPAPI logs)
            strategies.append({
                **_get_ytdlp_base_opts(), 
                "outtmpl": base_path + ".%(ext)s", 
                "format": FMT_STR, 
                "merge_output_format": "mp4", 
                **download_sections_opt
            })

            # 3. Youtube client bypass strategies (without browser cookies)
            if is_youtube:
                base_bypass = {
                    "quiet": True, 
                    "no_warnings": True, 
                    "ignoreconfig": True, 
                    "noplaylist": True, 
                    "outtmpl": base_path + ".%(ext)s", 
                    "format": FMT_STR_RELAXED, 
                    **download_sections_opt
                }
                if cookie_file:
                    base_bypass["cookiefile"] = cookie_file

                strategies += [
                    {**base_bypass, "extractor_args": {"youtube": {"player_client": ["ios"]}}, "http_headers": {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15"}},
                    {**base_bypass, "format": f"best[height<={height}][ext=mp4]/best[height<={height}]/best", "extractor_args": {"youtube": {"player_client": ["android"]}}},
                ]

            # 4. Fallback to browser cookies ONLY if first attempts fail
            if not cookie_file:
                strategies += [
                    {**_get_ytdlp_base_opts(), "outtmpl": base_path + ".%(ext)s", "format": FMT_STR, "cookiesfrombrowser": ("edge",), "merge_output_format": "mp4", **download_sections_opt},
                    {**_get_ytdlp_base_opts(), "outtmpl": base_path + ".%(ext)s", "format": FMT_STR, "cookiesfrombrowser": ("chrome",), "merge_output_format": "mp4", **download_sections_opt},
                ]

            # 5. Global fallbacks
            strategy_fallback_1 = {**_get_ytdlp_base_opts(), "outtmpl": base_path + ".%(ext)s", "format": FMT_STR_RELAXED, "merge_output_format": "mp4", **download_sections_opt}
            strategy_fallback_2 = {**_get_ytdlp_base_opts(), "outtmpl": base_path + ".%(ext)s", "format": f"bestvideo+bestaudio/best" if is_youtube else f"best[ext=mp4]/best", **download_sections_opt}
            strategy_fallback_3 = {**_get_ytdlp_base_opts(), "outtmpl": base_path + ".%(ext)s", "format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]}

            if cookie_file:
                strategy_fallback_1["cookiefile"] = cookie_file
                strategy_fallback_2["cookiefile"] = cookie_file
                strategy_fallback_3["cookiefile"] = cookie_file

            strategies += [strategy_fallback_1, strategy_fallback_2, strategy_fallback_3]

            last_error = None
            for idx, ydl_opts in enumerate(strategies):
                try:
                    logger.info(f"[YTDLPAdapter] Strategy {idx+1} for: {url}")
                    for old_file in glob.glob(base_path + ".*"):
                        if old_file != output_path:
                            try:
                                os.remove(old_file)
                            except Exception:
                                pass
                    try:
                        from app.utils.ffmpeg_utils import get_ffmpeg_path
                        ydl_opts["ffmpeg_location"] = os.path.dirname(get_ffmpeg_path())
                    except Exception:
                        pass

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])

                    downloaded_files = glob.glob(base_path + ".*")
                    if not downloaded_files:
                        raise FileNotFoundError(f"No output file: {base_path}.*")
                    actual_file = downloaded_files[0]
                    for f in downloaded_files:
                        if f.endswith(".mp4"):
                            actual_file = f
                            break
                        elif f.endswith((".webm", ".mkv")) and not actual_file.endswith(".mp4"):
                            actual_file = f

                    logger.info(f"[YTDLPAdapter] Downloaded: {actual_file} ({os.path.getsize(actual_file)} bytes)")
                    if actual_file != output_path:
                        if os.path.exists(output_path):
                            os.remove(output_path)
                        os.rename(actual_file, output_path)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        return output_path
                    raise FileNotFoundError("File missing or too small")
                except Exception as e:
                    last_error = e
                    logger.warning(f"[YTDLPAdapter] Strategy {idx+1} failed: {e}")
                    continue

            raise Exception(f"[YTDLPAdapter] All strategies failed. Last error: {last_error}")

    def _detect_source(self, url: str) -> str:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        source_map = {
            "youtube.com": "youtube", "youtu.be": "youtube",
            "facebook.com": "facebook", "fb.com": "facebook", "fb.watch": "facebook",
            "tiktok.com": "tiktok", "vt.tiktok.com": "tiktok",
            "vimeo.com": "vimeo",
            "bilibili.com": "bilibili", "b23.tv": "bilibili",
            "instagram.com": "instagram",
            "twitter.com": "twitter", "x.com": "twitter",
            "twitch.tv": "twitch",
            "dailymotion.com": "dailymotion",
            "reddit.com": "reddit", "v.redd.it": "reddit",
            "linkedin.com": "linkedin",
            "weibo.com": "weibo",
        }
        for k, v in source_map.items():
            if domain == k or domain.endswith("." + k):
                return v
        return "web"


def _hms_to_seconds(hms: str) -> float:
    """Convert HH:MM:SS or MM:SS to total seconds."""
    parts = hms.strip().split(":")
    try:
        parts = [float(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0]
    except (ValueError, IndexError):
        return 0.0

