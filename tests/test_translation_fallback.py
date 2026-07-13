import pytest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.services.dubbing_engine import translate_segments

@pytest.fixture
def clean_settings():
    # Save old config
    orig_gemini = settings.GEMINI_API_KEY

    yield settings

    # Restore old config
    settings.GEMINI_API_KEY = orig_gemini


def test_fallback_to_google_translate_when_gemini_fails(clean_settings):
    # Setup mock keys
    settings.GEMINI_API_KEY = "AQ.fake_gemini_key"

    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world"},
        {"start": 2.0, "end": 4.0, "text": "How are you"}
    ]

    # Mock requests: Gemini returns 429 (Too Many Requests)
    def mock_post(url, *args, **kwargs):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = Exception("HTTP Error 429: Too Many Requests")
        return mock_response

    # Mock GoogleTranslator
    mock_translator_inst = MagicMock()
    mock_translator_inst.translate.side_effect = ["Xin chào thế giới", "Bạn khỏe không"]

    with patch("requests.post", side_effect=mock_post), \
         patch("deep_translator.GoogleTranslator", return_value=mock_translator_inst):
        
        result = translate_segments(segments, target_lang="vi")
        
        assert result[0]["translation"] == "Xin chào thế giới"
        assert result[1]["translation"] == "Bạn khỏe không"


def test_fallback_to_google_translate_when_no_api_key(clean_settings):
    # Setup mock keys as empty
    settings.GEMINI_API_KEY = ""

    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world"}
    ]

    # Mock GoogleTranslator
    mock_translator_inst = MagicMock()
    mock_translator_inst.translate.return_value = "Xin chào thế giới (Google Translate)"

    with patch("deep_translator.GoogleTranslator", return_value=mock_translator_inst):
        result = translate_segments(segments, target_lang="vi")
        assert result[0]["translation"] == "Xin chào thế giới (Google Translate)"
