import urllib.request
import os
import shutil
import logging
from app.config import settings

logger = logging.getLogger(__name__)

def get_dummy_video(dest_path: str):
    """
    Sao chép tệp video mẫu (dummy) hợp lệ vào dest_path.
    Nếu tệp mẫu chưa tồn tại cục bộ, tự động tải xuống từ W3C test media (28 KB).
    """
    dummy_dir = settings.STORAGE_DIR / "dummy"
    os.makedirs(dummy_dir, exist_ok=True)
    dummy_file = dummy_dir / "dummy.mp4"
    
    if not dummy_file.exists():
        url = "https://github.com/web-platform-tests/wpt/raw/master/media/movie_5.mp4"
        try:
            logger.info(f"Đang tải video dummy mẫu từ {url}...")
            # Dùng timeout và header để tải an toàn
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10.0) as response:
                with open(dummy_file, "wb") as f:
                    f.write(response.read())
            logger.info("Đã tải thành công video dummy mẫu.")
        except Exception as e:
            logger.error(f"Lỗi khi tải video dummy từ {url}: {str(e)}")
            # Tạo file rỗng làm fallback cuối cùng
            with open(dummy_file, "wb") as f:
                f.write(b"")
                
    if dummy_file.exists():
        try:
            shutil.copy(str(dummy_file), dest_path)
        except Exception as e:
            logger.error(f"Không thể copy file dummy đến {dest_path}: {str(e)}")
