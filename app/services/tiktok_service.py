import base64
import os
import httpx
import logging

logger = logging.getLogger(__name__)

# Danh sách các giọng TikTok/CapCut Việt và Anh nổi tiếng
TIKTOK_VOICES = [
    {"id": "vi_vn_002", "name": "Cô Gái Hoạt Ngôn (CapCut Việt)", "gender": "female", "lang": "vi", "desc": "Giọng nữ năng động, hoạt ngôn cực kỳ đặc trưng trên CapCut và TikTok Việt Nam."},
    {"id": "vi_vn_001", "name": "Chàng Trai Kể Chuyện (CapCut Việt)", "gender": "male", "lang": "vi", "desc": "Giọng nam trầm ấm, rõ ràng, thích hợp làm tin tức hoặc kể chuyện."},
    {"id": "en_us_001", "name": "CapCut Nữ (Mỹ)", "gender": "female", "lang": "en", "desc": "Giọng nữ tiếng Anh chuẩn Mỹ ngọt ngào."},
    {"id": "en_us_006", "name": "CapCut Nam (Mỹ)", "gender": "male", "lang": "en", "desc": "Giọng nam tiếng Anh trầm ấm, chuẩn Mỹ."},
    {"id": "en_us_ghostface", "name": "CapCut Ghostface", "gender": "male", "lang": "en", "desc": "Giọng Ghostface ma mị, kinh dị trong phim Scream."}
]

class TiktokService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TiktokService, cls).__new__(cls)
        return cls._instance

    def generate_speech(self, text: str, voice_id: str, output_path: str) -> bool:
        """
        Sinh giọng đọc bằng API TikTok/CapCut công cộng.
        """
        url = "https://tiktok-tts.weilnet.workers.dev/api/generation"
        
        # TikTok API giới hạn tối đa 300 ký tự mỗi đoạn
        clean_text = text.strip()
        if len(clean_text) > 290:
            clean_text = clean_text[:290] + "..."
            
        payload = {
            "text": clean_text,
            "voice": voice_id
        }
        
        try:
            logger.info(f"Gửi request sinh giọng TikTok cho voice {voice_id}...")
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                
            if response.status_code != 200:
                logger.error(f"TikTok API trả về status code {response.status_code}: {response.text}")
                return False
                
            result = response.json()
            if not result.get("success"):
                logger.error(f"TikTok API báo lỗi: {result.get('error')}")
                return False
                
            audio_base64 = result.get("data")
            if not audio_base64:
                logger.error("Không nhận được dữ liệu âm thanh từ TikTok API.")
                return False
                
            audio_data = base64.b64decode(audio_base64)
            
            # Ghi ra file
            with open(output_path, "wb") as f:
                f.write(audio_data)
                
            logger.info(f"Đã sinh giọng TikTok thành công: {output_path} ({len(audio_data)} bytes)")
            return True
            
        except Exception as e:
            logger.error(f"Lỗi khi gọi TikTok TTS API: {e}")
            return False
