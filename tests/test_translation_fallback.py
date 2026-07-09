import pytest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.services.dubbing_engine import translate_segments

@pytest.fixture
def clean_settings():
    # Lưu cấu hình cũ
    orig_gemini = settings.GEMINI_API_KEY
    orig_groq = settings.GROQ_API_KEY
    orig_openrouter = settings.OPENROUTER_API_KEY
    orig_github = settings.GITHUB_API_KEY
    orig_cohere = settings.COHERE_API_KEY

    yield settings

    # Khôi phục cấu hình cũ
    settings.GEMINI_API_KEY = orig_gemini
    settings.GROQ_API_KEY = orig_groq
    settings.OPENROUTER_API_KEY = orig_openrouter
    settings.GITHUB_API_KEY = orig_github
    settings.COHERE_API_KEY = orig_cohere


def test_fallback_to_groq_when_gemini_fails(clean_settings):
    # Thiết lập mock keys
    settings.GEMINI_API_KEY = "AQ.fake_gemini_key"
    settings.GROQ_API_KEY = "gsk_fake_groq_key"
    settings.OPENROUTER_API_KEY = ""
    settings.GITHUB_API_KEY = ""
    settings.COHERE_API_KEY = ""

    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world"},
        {"start": 2.0, "end": 4.0, "text": "How are you"}
    ]

    # Mock request: Gemini lỗi 429, Groq thành công 200
    def mock_post(url, *args, **kwargs):
        mock_response = MagicMock()
        if "generativelanguage.googleapis.com" in url:
            mock_response.status_code = 429
            mock_response.raise_for_status.side_effect = Exception("HTTP Error 429: Too Many Requests")
        elif "api.groq.com" in url:
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{
                    "message": {
                        "content": '["Xin chào thế giới", "Bạn khỏe không"]'
                    }
                }]
            }
        return mock_response

    with patch("requests.post", side_effect=mock_post):
        result = translate_segments(segments, target_lang="vi")
        
        assert result[0]["translation"] == "Xin chào thế giới"
        assert result[1]["translation"] == "Bạn khỏe không"


def test_fallback_to_google_translate_when_all_llms_fail(clean_settings):
    # Thiết lập mock keys
    settings.GEMINI_API_KEY = "AQ.fake_gemini_key"
    settings.GROQ_API_KEY = "gsk_fake_groq_key"
    settings.OPENROUTER_API_KEY = ""
    settings.GITHUB_API_KEY = ""
    settings.COHERE_API_KEY = ""

    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world"}
    ]

    # Mock all HTTP calls to fail
    def mock_post(url, *args, **kwargs):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Internal Server Error")
        return mock_response

    # Mock GoogleTranslator
    mock_translator_inst = MagicMock()
    mock_translator_inst.translate.return_value = "Xin chào thế giới (Google Translate)"

    with patch("requests.post", side_effect=mock_post), \
         patch("deep_translator.GoogleTranslator", return_value=mock_translator_inst):
        
        result = translate_segments(segments, target_lang="vi")
        
        assert result[0]["translation"] == "Xin chào thế giới (Google Translate)"
