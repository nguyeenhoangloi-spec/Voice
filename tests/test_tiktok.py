import os
import sys

# Thêm thư mục gốc vào python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.tiktok_service import TiktokService

def test_tiktok_tts():
    print("Khoi tao TiktokService...")
    service = TiktokService()
    
    output_dir = "storage/temp"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "test_tiktok_output.mp3")
    
    # Neu co session_id trong .env thi test giong Viet vi_vn_002
    # Con neu khong co thi test giong My en_us_001 (khong can session_id qua proxy)
    session_id = os.getenv("TIKTOK_SESSION_ID")
    if session_id:
        voice = "vi_vn_002"
        text = "Xin chao cac ban! Day la ban long tieng nghe thu bang giong nu hoat ngon cua CapCut."
        print(f"Co TIKTOK_SESSION_ID. Dang sinh giong CapCut Viet '{voice}'...")
    else:
        voice = "en_us_001"
        text = "Hello! This is a test of CapCut voice without session ID."
        print(f"Khong co TIKTOK_SESSION_ID. Dang sinh giong CapCut My '{voice}'...")
        
    success = service.generate_speech(text, voice, output_path)
    
    if success and os.path.exists(output_path):
        size = os.path.getsize(output_path)
        print(f"Sinh giong thanh cong! File luu tai: {output_path} ({size} bytes)")
        assert size > 100
    else:
        print("Sinh giong that bai.")
        assert False

if __name__ == "__main__":
    test_tiktok_tts()
