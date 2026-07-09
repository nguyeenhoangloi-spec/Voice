import base64
import os
import httpx
import logging

logger = logging.getLogger(__name__)

# Danh sách các giọng TikTok/CapCut Việt và Anh nổi tiếng
TIKTOK_VOICES = [
    {"id": "vi_vn_002", "name": "Cô Gái Hoạt Ngôn (CapCut Việt)", "gender": "female", "lang": "vi", "desc": "Giọng nữ năng động, hoạt ngôn cực kỳ đặc trưng trên CapCut và TikTok Việt Nam. (Cần cấu hình TIKTOK_SESSION_ID trong file .env)"},
    {"id": "vi_vn_001", "name": "Chàng Trai Kể Chuyện (CapCut Việt)", "gender": "male", "lang": "vi", "desc": "Giọng nam trầm ấm, rõ ràng, thích hợp làm tin tức hoặc kể chuyện. (Cần cấu hình TIKTOK_SESSION_ID trong file .env)"},
    {"id": "en_us_001", "name": "CapCut Nữ (Mỹ)", "gender": "female", "lang": "en", "desc": "Giọng nữ tiếng Anh chuẩn Mỹ ngọt ngào."},
    {"id": "en_us_006", "name": "CapCut Nam (Mỹ)", "gender": "male", "lang": "en", "desc": "Giọng nam tiếng Anh trầm ấm, chuẩn Mỹ."},
    {"id": "en_us_ghostface", "name": "CapCut Ghostface", "gender": "male", "lang": "en", "desc": "Giọng Ghostface ma mị, kinh dị trong phim Scream."}
]


def get_session_id_from_browsers() -> str:
    """Tự động quét các trình duyệt trên máy để lấy cookie sessionid của TikTok"""
    try:
        import browser_cookie3
        browsers = [
            browser_cookie3.chrome,
            browser_cookie3.edge,
            browser_cookie3.firefox,
            browser_cookie3.opera,
            browser_cookie3.chromium
        ]
        logger.info("[TikTok TTS] Đang quét cookie của trình duyệt để tìm TikTok sessionid...")
        for browser_fn in browsers:
            try:
                cj = browser_fn(domain_name='.tiktok.com')
                for cookie in cj:
                    if cookie.name == 'sessionid':
                        val = cookie.value
                        if val:
                            logger.info(f"[TikTok TTS] Đã tự động lấy thành công sessionid từ trình duyệt: {val[:6]}...{val[-6:]}")
                            return val
            except Exception:
                continue
    except ImportError:
        logger.warning("[TikTok TTS] Chưa cài đặt browser-cookie3.")
    except Exception as e:
        logger.error(f"[TikTok TTS] Lỗi khi quét cookie trình duyệt: {e}")
    return None


def update_env_session_id(sid: str):
    """Tự động cập nhật sessionid mới vào file .env"""
    env_path = r'd:\Voice_AI\.env'
    if not os.path.exists(env_path):
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(f"TIKTOK_SESSION_ID={sid}\n")
        os.environ["TIKTOK_SESSION_ID"] = sid
        return
        
    with open(env_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith("TIKTOK_SESSION_ID="):
            lines[i] = f"TIKTOK_SESSION_ID={sid}\n"
            updated = True
            break
            
    if not updated:
        lines.append(f"\nTIKTOK_SESSION_ID={sid}\n")
        
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    os.environ["TIKTOK_SESSION_ID"] = sid
    logger.info("[TikTok TTS] Đã lưu TIKTOK_SESSION_ID mới vào file .env thành công.")

class TiktokService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TiktokService, cls).__new__(cls)
        return cls._instance

    def generate_speech(self, text: str, voice_id: str, output_path: str) -> bool:
        """
        Sinh giọng đọc bằng API TikTok/CapCut gốc (gửi trực tiếp từ IP Việt Nam để tránh Geo-blocking).
        Tích hợp tính năng tự động trích xuất cookie và tự vá lỗi khi sessionid hết hạn.
        """
        clean_text = text.strip()
        if len(clean_text) > 290:
            clean_text = clean_text[:290] + "..."
            
        # Lấy session_id từ .env
        session_id = os.getenv("TIKTOK_SESSION_ID")
        if not session_id or session_id.strip() == "":
            session_id = get_session_id_from_browsers()
            
        def call_tiktok_api(sid) -> tuple[bool, str]:
            url_direct = "https://api16-normal-c-useast1a.tiktokv.com/media/api/text/speech/invoke/"
            headers = {
                "User-Agent": "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_US; SM-G977N; Build/LMY48Z; deliberate)",
                "Content-Type": "application/json"
            }
            if sid:
                headers["Cookie"] = f"sessionid={sid.strip()}"
            else:
                if voice_id.startswith("vi_vn_"):
                    logger.warning("[TikTok TTS] Cảnh báo: Bạn đang gọi giọng tiếng Việt CapCut nhưng chưa cấu hình TIKTOK_SESSION_ID trong file .env và không tìm thấy cookie trong trình duyệt.")
            
            params = {"aid": "1233"}
            payload = {
                "text_speaker": voice_id,
                "req_text": clean_text,
                "speaker_map_type": 0
            }
            try:
                with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                    response = client.post(url_direct, params=params, json=payload, headers=headers)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("message") == "success" and result.get("data", {}).get("v_str"):
                        audio_base64 = result["data"]["v_str"]
                        audio_data = base64.b64decode(audio_base64)
                        with open(output_path, "wb") as f:
                            f.write(audio_data)
                        return True, "success"
                    else:
                        return False, result.get("message", "unknown error")
                return False, f"HTTP {response.status_code}"
            except Exception as e:
                return False, str(e)

        # Lượt gọi 1
        success, err_msg = call_tiktok_api(session_id)
        
        # Nếu thất bại vì lỗi liên quan đến Session ID, tự động quét và thử lại lần 2
        if not success and (err_msg == "Couldn't load speech. Try again." or "session" in err_msg or "supported" in err_msg or not session_id):
            logger.info("[TikTok TTS] Phát hiện lỗi Session ID. Đang thử tự động quét trình duyệt lấy sessionid mới...")
            auto_sid = get_session_id_from_browsers()
            if auto_sid and auto_sid != session_id:
                logger.info("[TikTok TTS] Quét thành công sessionid mới từ trình duyệt. Tiến hành gọi lại lần 2...")
                success, err_msg = call_tiktok_api(auto_sid)
                if success:
                    try:
                        update_env_session_id(auto_sid)
                    except Exception as env_err:
                        logger.error(f"[TikTok TTS] Không thể lưu sessionid mới vào .env: {env_err}")

        if success:
            logger.info(f"Đã sinh giọng TikTok gốc thành công: {output_path}")
            return True
        else:
            logger.warning(f"TikTok API gốc trả về lỗi: {err_msg}")
            
        # 2. Fallback: Thử gọi qua Cloudflare Worker (hoạt động tốt với các giọng tiếng Anh không cần session_id)
        url_fallback = "https://tiktok-tts.weilnet.workers.dev/api/generation"
        payload_fallback = {
            "text": clean_text,
            "voice": voice_id
        }
        try:
            logger.info(f"Thử gọi fallback qua proxy weilnet cho {voice_id}...")
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.post(url_fallback, json=payload_fallback)
                
            if response.status_code == 200:
                result = response.json()
                if result.get("success") and result.get("data"):
                    audio_base64 = result.get("data")
                    audio_data = base64.b64decode(audio_base64)
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    logger.info(f"Sinh giọng qua proxy weilnet thành công: {output_path}")
                    return True
            logger.error(f"Fallback proxy cũng thất bại cho giọng {voice_id}.")
        except Exception as e:
            logger.error(f"Lỗi khi gọi fallback proxy: {e}")
            
        return False
