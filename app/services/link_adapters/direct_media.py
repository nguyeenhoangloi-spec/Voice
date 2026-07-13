import httpx
import os
import subprocess
import json
from urllib.parse import urlparse
from app.services.link_adapters.base import BaseAdapter

class DirectMediaAdapter(BaseAdapter):
    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        media_extensions = [".mp4", ".webm", ".mp3", ".wav", ".ogg", ".aac", ".m4a"]
        return any(path.endswith(ext) for ext in media_extensions)

    def extract_metadata(self, url: str) -> dict:
        try:
            # Gửi request HEAD để kiểm tra kích thước và loại dữ liệu
            with httpx.Client(timeout=10.0) as client:
                res = client.head(url, follow_redirects=True)
                content_type = res.headers.get("content-type", "").lower()
                content_length = int(res.headers.get("content-length", 0))

            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "direct_media"

            # Sử dụng ffprobe để lấy thời lượng từ xa nếu server hỗ trợ range request, 
            # hoặc tải tạm vài KB đầu để probe. Để đơn giản và an toàn, ta gọi ffprobe trực tiếp URL.
            duration = 0.0
            try:
                cmd = [
                    "ffprobe", "-v", "quiet", "-print_format", "json", 
                    "-show_format", "-show_streams", url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
                if result.returncode == 0:
                    probe_data = json.loads(result.stdout)
                    duration = float(probe_data.get("format", {}).get("duration", 0.0))
            except Exception:
                pass # Bỏ qua nếu ffprobe thất bại khi đọc URL trực tiếp

            return {
                "success": True,
                "title": filename,
                "thumbnail": "", # Link trực tiếp không có thumbnail mặc định
                "duration": duration,
                "source": "direct_media",
                "content_type": content_type,
                "file_size": content_length
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Lỗi lấy thông tin file media: {str(e)}"
            }

    def download(self, url: str, output_path: str, **kwargs) -> str:
        # Tải file trực tiếp qua HTTP
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
        return output_path
