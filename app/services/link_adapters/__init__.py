from app.services.link_adapters.youtube import YouTubeAdapter
from app.services.link_adapters.direct_media import DirectMediaAdapter
from app.services.link_adapters.webpage import WebpageAdapter

# Đăng ký các adapter theo thứ tự ưu tiên kiểm tra
ADAPTER_REGISTRY = [
    YouTubeAdapter(),
    DirectMediaAdapter(),
    WebpageAdapter() # Webpage là fallback cuối cùng
]

def get_adapter_for_url(url: str):
    """Tìm adapter phù hợp cho URL cụ thể"""
    for adapter in ADAPTER_REGISTRY:
        if adapter.can_handle(url):
            return adapter
    return None
