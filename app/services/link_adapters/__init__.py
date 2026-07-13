from app.services.link_adapters.direct_media import DirectMediaAdapter
from app.services.link_adapters.ytdlp import YTDLPAdapter
from app.services.link_adapters.webpage import WebpageAdapter

# Đăng ký các adapter theo thứ tự ưu tiên kiểm tra:
# 1. DirectMediaAdapter — file media trực tiếp (.mp4, .mp3, v.v.) — kiểm tra trước để tránh gọi yt-dlp không cần thiết
# 2. YTDLPAdapter — xử lý YouTube VÀ hơn 1000 nền tảng khác (Facebook, TikTok, Vimeo, Bilibili...)
# 3. WebpageAdapter — fallback cuối cùng: quét HTML thô
ADAPTER_REGISTRY = [
    DirectMediaAdapter(),
    YTDLPAdapter(),
    WebpageAdapter()  # Fallback cuối cùng
]

def get_adapter_for_url(url: str):
    """Tìm adapter phù hợp cho URL cụ thể"""
    for adapter in ADAPTER_REGISTRY:
        if adapter.can_handle(url):
            return adapter
    return None
