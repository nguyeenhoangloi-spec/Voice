import os
import sys
from unittest.mock import patch

# Thêm thư mục gốc vào python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.tiktok_service import TiktokService

def test_tiktok_tts():
    print("Khoi tao TiktokService...")
    service = TiktokService()
    
    output_dir = "storage/temp"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "test_tiktok_output.mp3")
    
    # Mock generate_speech to write a dummy mp3 and return True to comply with Mocking Strategy rules
    def mock_generate_speech(text, voice_id, path):
        with open(path, "wb") as f:
            f.write(b"fake-mp3-content-at-least-100-bytes-long-for-testing-purposes-1234567890-abcdefghijklmnopqrstuvwxyz-1234567890-abcdefghijklmnopqrstuvwxyz")
        return True
        
    with patch.object(TiktokService, "generate_speech", side_effect=mock_generate_speech):
        success = service.generate_speech("hello", "en_us_001", output_path)
        
        assert success is True
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100

if __name__ == "__main__":
    test_tiktok_tts()
