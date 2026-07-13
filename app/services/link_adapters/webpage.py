import httpx
import re
from urllib.parse import urljoin, urlparse
from app.services.link_adapters.base import BaseAdapter
from app.services.link_adapters.direct_media import DirectMediaAdapter

class WebpageAdapter(BaseAdapter):
    def can_handle(self, url: str) -> bool:
        # Nhận diện bất kỳ URL HTTP/HTTPS hợp lệ nào
        parsed = urlparse(url)
        return parsed.scheme in ["http", "https"]

    def extract_metadata(self, url: str) -> dict:
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                res = client.get(url)
                html = res.text

            # 1. Tìm thẻ og:video hoặc og:audio trong meta tags
            og_media = re.search(r'<meta\s+property=["\']og:(video|audio)["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
            media_url = None
            if og_media:
                media_url = og_media.group(2)
            else:
                # 2. Tìm thẻ <video src="..."> hoặc <source src="...">
                video_src = re.search(r'<video[^>]*?src=["\'](.*?)["\']', html, re.IGNORECASE)
                if video_src:
                    media_url = video_src.group(1)
                else:
                    source_src = re.search(r'<source[^>]*?src=["\'](.*?)["\']', html, re.IGNORECASE)
                    if source_src:
                        media_url = source_src.group(1)

            if not media_url:
                return {
                    "success": False,
                    "error": "Không tìm thấy thẻ video hoặc audio hợp lệ trên trang web này."
                }

            # Giải quyết URL tương đối (relative path)
            media_url = urljoin(url, media_url)
            
            # Sử dụng DirectMediaAdapter để trích xuất thông tin chi tiết của media_url
            direct_adapter = DirectMediaAdapter()
            meta = direct_adapter.extract_metadata(media_url)
            if meta.get("success"):
                meta["original_page_url"] = url
                meta["source"] = "webpage"
                meta["media_url"] = media_url
            return meta

        except Exception as e:
            return {
                "success": False,
                "error": f"Lỗi quét trang web: {str(e)}"
            }

    def download(self, url: str, output_path: str, **kwargs) -> str:
        # Lấy lại metadata để lấy link media thật
        meta = self.extract_metadata(url)
        if not meta.get("success") or "media_url" not in meta:
            raise Exception("Không thể tìm thấy liên kết media trực tiếp để tải xuống.")
            
        media_url = meta["media_url"]
        direct_adapter = DirectMediaAdapter()
        return direct_adapter.download(media_url, output_path)
