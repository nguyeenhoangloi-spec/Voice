import yt_dlp
import os
import glob
import logging
import requests
import re
from urllib.parse import urlparse
from app.services.link_adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


def _get_ydl_douyin_opts() -> dict:
    """Base yt-dlp options for Douyin/TikTok to avoid blocks and HTTP 403 errors"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreconfig': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/',
        },
    }
    return opts


def _get_ydl_douyin_mobile_opts(platform: str = "android") -> dict:
    """Get mobile user-agent options to bypass desktop cookie requirements"""
    ua = (
        'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'
        if platform == "android" else
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
    )
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreconfig': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': ua,
            'Referer': 'https://v.douyin.com/',
        },
    }
    return opts


def normalize_douyin_url(url: str) -> str:
    """
    Theo vết chuyển hướng và chuẩn hóa URL Douyin về dạng www.douyin.com/video/{id}
    để yt-dlp nhận diện chính xác và tránh lỗi "Unsupported URL".
    """
    try:
        # 1. Theo vết chuyển hướng nếu là link rút gọn v.douyin.com
        if "v.douyin.com" in url:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.douyin.com/',
            }
            # Sử dụng requests.head hoặc requests.get để lấy URL thật
            r = requests.head(url, allow_redirects=True, headers=headers, timeout=5)
            url = r.url
            logger.info(f"Redirected v.douyin.com to: {url}")

        # 2. Tìm ID video trong URL thực tế
        # Thường có dạng: /video/7377884841961672002 hoặc /share/video/7377884841961672002
        match = re.search(r'(?:video|note|share/video)/(\d+)', url)
        if match:
            video_id = match.group(1)
            normalized = f"https://www.douyin.com/video/{video_id}"
            logger.info(f"Normalized Douyin URL to: {normalized}")
            return normalized
            
    except Exception as e:
        logger.warning(f"Failed to normalize Douyin URL: {e}")
        
    return url


# ---------------------------------------------------------------------------
# cobalt.tools fallback helpers (Layer 2)
# ---------------------------------------------------------------------------

COBALT_API_URL = "https://cobalt.tools/api/json"
COBALT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _call_cobalt_api(url: str) -> dict | None:
    """
    Call cobalt.tools API to get a direct video download URL.
    Returns the parsed JSON response or None on failure.
    Layer 2 fallback - no user cookies required, managed by cobalt.tools backend.
    """
    try:
        payload = {"url": url, "vQuality": "max"}
        resp = requests.post(
            COBALT_API_URL,
            json=payload,
            headers=COBALT_HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"cobalt.tools returned HTTP {resp.status_code}")
            return None
        data = resp.json()
        logger.info(f"cobalt.tools response status: {data.get('status')}")
        return data
    except Exception as e:
        logger.warning(f"cobalt.tools API call failed: {e}")
        return None


def _cobalt_extract_metadata(url: str) -> dict | None:
    """
    Attempt to extract metadata via cobalt.tools.
    Returns a metadata dict compatible with extract_metadata() contract, or None.
    """
    data = _call_cobalt_api(url)
    if not data:
        return None

    status = data.get("status")
    # cobalt returns "redirect" or "stream" with a direct URL
    if status in ("redirect", "stream", "picker") and data.get("url"):
        direct_url = data["url"]
        return {
            "success": True,
            "title": data.get("filename", "Douyin Video"),
            "thumbnail": "",
            "duration": 0,  # cobalt.tools does not expose duration; will be probed later
            "source": "douyin",
            "author": "Unknown",
            "description": "",
            "_cobalt_direct_url": direct_url,  # internal key for download step
        }
    return None


def _cobalt_download(url: str, output_path: str) -> str:
    """
    Download video via cobalt.tools direct URL.
    Returns output_path on success, raises Exception on failure.
    """
    data = _call_cobalt_api(url)
    if not data:
        raise Exception("cobalt.tools API returned no data")

    status = data.get("status")
    direct_url = data.get("url")

    if status not in ("redirect", "stream", "picker") or not direct_url:
        raise Exception(f"cobalt.tools unexpected status: {status} | url: {direct_url}")

    logger.info(f"Downloading via cobalt.tools direct URL: {direct_url[:80]}...")
    try:
        with requests.get(direct_url, stream=True, timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise FileNotFoundError("cobalt.tools download produced empty file")

        logger.info(f"cobalt.tools download success: {output_path} ({os.path.getsize(output_path) // 1024} KB)")
        return output_path
    except Exception as e:
        # Clean up partial file
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        raise Exception(f"cobalt.tools download stream failed: {e}")


# ---------------------------------------------------------------------------
# DouyinAdapter
# ---------------------------------------------------------------------------

class DouyinAdapter(BaseAdapter):
    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return any(x in domain for x in ["douyin.com", "iesdouyin.com", "tiktok.com"])

    def _get_cookie_file(self) -> str | None:
        """Find cookies.txt in common directories using absolute project root"""
        # Determine the project root directory (d:\Voice_AI)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        
        paths = [
            os.path.join(project_root, "cookies.txt"),
            os.path.join(project_root, "storage", "cookies.txt"),
            "cookies.txt",
            "storage/cookies.txt"
        ]
        for p in paths:
            if os.path.exists(p):
                return os.path.abspath(p)
        return None

    def extract_metadata(self, url: str) -> dict:
        url = normalize_douyin_url(url)
        cookie_file = self._get_cookie_file()
        strategies = []

        # Strategy 1 (Highest priority): Use custom cookies.txt if exists
        if cookie_file:
            logger.info(f"Found local cookies.txt: {cookie_file}. Using it as primary strategy.")
            opts_cookie = _get_ydl_douyin_opts().copy()
            opts_cookie['cookiefile'] = cookie_file
            strategies.append(opts_cookie)

        # Strategy 2 & 3: Mobile User-Agents (often bypass cookie checks)
        strategies.append(_get_ydl_douyin_mobile_opts(platform="android"))
        strategies.append(_get_ydl_douyin_mobile_opts(platform="ios"))

        # Fallback strategies
        strategies.extend([
            _get_ydl_douyin_opts(),  # Standard desktop no cookies
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('chrome',)},  # Chrome
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('edge',)},  # Edge
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('firefox',)},  # Firefox
        ])

        last_error = None
        for idx, ydl_opts in enumerate(strategies):
            try:
                strategy_name = f"cookies.txt" if (cookie_file and idx == 0) else f"strategy {idx + 1}"
                logger.info(f"Extracting Douyin metadata using {strategy_name} for: {url}")
                
                ydl_opts_copy = ydl_opts.copy()
                ydl_opts_copy['skip_download'] = True
                with yt_dlp.YoutubeDL(ydl_opts_copy) as ydl:
                    info = ydl.extract_info(url, download=False)
                    # Try to get thumbnail or fallback
                    thumbnail = info.get("thumbnail", "")
                    if not thumbnail and info.get("thumbnails"):
                        thumbnail = info["thumbnails"][0].get("url", "")
                    return {
                        "success": True,
                        "title": info.get("title", "Douyin/TikTok Video"),
                        "thumbnail": thumbnail,
                        "duration": info.get("duration", 0),
                        "source": "douyin",
                        "author": info.get("uploader", "Unknown"),
                        "description": ((info.get("description", "") or "")[:200] + "...")
                    }
            except Exception as e:
                last_error = e
                logger.warning(f"Douyin metadata strategy {idx + 1} failed: {e}")
                continue

        # --- LAYER 2: cobalt.tools API fallback ---
        logger.warning(f"All yt-dlp strategies failed. Trying cobalt.tools API fallback for: {url}")
        cobalt_meta = _cobalt_extract_metadata(url)
        if cobalt_meta:
            logger.info("cobalt.tools metadata extraction succeeded.")
            return cobalt_meta

        return {
            "success": False,
            "error": f"Douyin metadata error: {str(last_error)}",
            "fallback_needed": True,  # Signal to UI that upload fallback is needed
        }

    def download(self, url: str, output_path: str) -> str:
        url = normalize_douyin_url(url)
        base_path, _ = os.path.splitext(output_path)
        cookie_file = self._get_cookie_file()
        strategies = []

        # Strategy 1 (Highest priority): Use custom cookies.txt if exists
        if cookie_file:
            logger.info(f"Found local cookies.txt: {cookie_file}. Using it as primary download strategy.")
            opts_cookie = _get_ydl_douyin_opts().copy()
            opts_cookie['cookiefile'] = cookie_file
            strategies.append(opts_cookie)

        # Strategy 2 & 3: Mobile User-Agents
        strategies.append(_get_ydl_douyin_mobile_opts(platform="android"))
        strategies.append(_get_ydl_douyin_mobile_opts(platform="ios"))

        # Fallbacks
        strategies.extend([
            _get_ydl_douyin_opts(),
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('chrome',)},
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('edge',)},
            {**_get_ydl_douyin_opts(), 'cookiesfrombrowser': ('firefox',)},
        ])

        # Inject FFmpeg path if available
        ffmpeg_dir = None
        try:
            from app.utils.ffmpeg_utils import get_ffmpeg_path
            ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
        except Exception:
            pass

        last_error = None
        for idx, ydl_opts in enumerate(strategies):
            try:
                ydl_opts_copy = ydl_opts.copy()
                ydl_opts_copy.update({
                    'outtmpl': base_path + '.%(ext)s',
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                })
                if ffmpeg_dir:
                    ydl_opts_copy['ffmpeg_location'] = ffmpeg_dir

                strategy_name = f"cookies.txt" if (cookie_file and idx == 0) else f"strategy {idx + 1}"
                logger.info(f"Douyin download using {strategy_name} for: {url}")
                
                # Dọn dẹp file tạm trước
                for old_file in glob.glob(base_path + ".*"):
                    if old_file != output_path:
                        try:
                            os.remove(old_file)
                        except Exception:
                            pass

                with yt_dlp.YoutubeDL(ydl_opts_copy) as ydl:
                    ydl.download([url])

                # Find file
                downloaded_files = glob.glob(base_path + ".*")
                if not downloaded_files:
                    raise FileNotFoundError(f"No file produced for pattern: {base_path}.*")

                actual_file = downloaded_files[0]
                for f in downloaded_files:
                    if f.endswith('.mp4'):
                        actual_file = f
                        break
                    elif f.endswith(('.webm', '.mkv')):
                        actual_file = f

                # Rename to target path
                if actual_file != output_path:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(actual_file, output_path)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Douyin download success: {output_path}")
                    return output_path
                else:
                    raise FileNotFoundError("Downloaded file is missing or too small")

            except Exception as e:
                last_error = e
                logger.warning(f"Douyin download strategy {idx + 1} failed: {e}")
                continue

        # --- LAYER 2: cobalt.tools API fallback ---
        logger.warning(f"All yt-dlp download strategies failed. Trying cobalt.tools API fallback for: {url}")
        try:
            return _cobalt_download(url, output_path)
        except Exception as cobalt_error:
            logger.error(f"cobalt.tools download also failed: {cobalt_error}")
            # Raise a special sentinel exception that the pipeline worker catches
            # to set job status = "waiting_upload" instead of "failed"
            raise Exception(
                f"DOWNLOAD_FAILED_NEED_UPLOAD|All Douyin download strategies failed. "
                f"yt-dlp error: {last_error} | cobalt.tools error: {cobalt_error}"
            )
