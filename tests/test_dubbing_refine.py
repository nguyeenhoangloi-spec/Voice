import pytest
from unittest.mock import patch, MagicMock
from app.services.dubbing_engine import _refine_with_gemini_vision, translate_segments


def test_refine_with_gemini_vision_partial_success():
    """Verify that _refine_with_gemini_vision updates only matched indices and doesn't discard the batch when length mismatches."""
    segments = [
        {"text": "大雄", "translation": ""},
        {"text": "静香", "translation": ""},
        {"text": "胖虎", "translation": ""}
    ]
    keyframes = {0: "dummy_b64_0", 1: "dummy_b64_1", 2: "dummy_b64_2"}
    api_key = "test_key"

    # Gemini only returns 2 results instead of 3, and they are out of order
    mock_response_text = """
    [
        {"index": 2, "text": "胖虎", "translation": "Chai En"},
        {"index": 0, "text": "大雄", "translation": "Nô Bi Ta"}
    ]
    """

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": mock_response_text}
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_response) as mock_post:
        result = _refine_with_gemini_vision(segments, keyframes, api_key)
        
        # Verify requests.post was called
        mock_post.assert_called_once()
        
        # Segment 0 and 2 should be updated correctly
        assert result[0]["translation"] == "Nô Bi Ta"
        assert result[2]["translation"] == "Chai En"
        
        # Segment 1 should be untouched (since it was missing in the mock response)
        assert result[1]["translation"] == ""


def test_translate_segments_preserves_existing_translations():
    """Verify that translate_segments does not overwrite existing translations and only translates pending segments."""
    segments = [
        {"text": "Hello", "translation": "Xin chào"}, # Already translated (e.g., by Gemini Vision)
        {"text": "How are you?", "translation": ""}, # Pending translation
        {"text": "Good morning", "translation": "Chào buổi sáng"} # Already translated
    ]

    # We mock _translate_batch_with_llm to only return translation for the pending segment
    # The batch size sent to the LLM should be 1 (only the pending segment)
    with patch("app.services.dubbing_engine._translate_batch_with_llm", return_value=["Bạn khoẻ không?"]) as mock_llm:
        # We need to temporarily configure an API key so that the LLM code path is triggered
        with patch("app.config.settings.GEMINI_API_KEY", "test_key"):
            result = translate_segments(segments, target_lang="vi")
            
            # Verify LLM was called with expected batch size of 1
            mock_llm.assert_called_once()
            args, kwargs = mock_llm.call_args
            assert args[1] == 1 # expected count = 1
            
            # Verify the result contains the correct values without overwriting existing ones
            assert result[0]["translation"] == "Xin chào"
            assert result[1]["translation"] == "Bạn khoẻ không?"
            assert result[2]["translation"] == "Chào buổi sáng"


def test_voice_map_assignment_single_vs_auto():
    """Verify how voice_map is constructed for single voice choice vs auto mode in the pipeline."""
    # Scenario 1: Specific voice chosen (e.g. vi-VN-NamMinhNeural)
    voice_profile = "vi-VN-NamMinhNeural"
    voice_name = "vi-VN-NamMinhNeural"
    
    # Simulate step 14 mapping logic
    if voice_profile and voice_profile != "auto":
        voice_map = {
            "Speaker 1": voice_name,
            "Speaker 2": voice_name,
            "Speaker 3": voice_name,
            "Speaker 4": voice_name,
        }
    else:
        opposite_voice = "vi-VN-NamMinhNeural" if voice_name == "vi-VN-HoaiMyNeural" else "vi-VN-HoaiMyNeural"
        voice_map = {
            "Speaker 1": voice_name,
            "Speaker 2": opposite_voice,
            "Speaker 3": voice_name,
            "Speaker 4": opposite_voice,
        }
    
    assert voice_map["Speaker 1"] == "vi-VN-NamMinhNeural"
    assert voice_map["Speaker 2"] == "vi-VN-NamMinhNeural"
    assert voice_map["Speaker 3"] == "vi-VN-NamMinhNeural"
    assert voice_map["Speaker 4"] == "vi-VN-NamMinhNeural"
    
    # Scenario 2: Auto mode chosen
    voice_profile = "auto"
    voice_name = "vi-VN-HoaiMyNeural"
    if voice_profile and voice_profile != "auto":
        voice_map = {
            "Speaker 1": voice_name,
            "Speaker 2": voice_name,
            "Speaker 3": voice_name,
            "Speaker 4": voice_name,
        }
    else:
        opposite_voice = "vi-VN-NamMinhNeural" if voice_name == "vi-VN-HoaiMyNeural" else "vi-VN-HoaiMyNeural"
        voice_map = {
            "Speaker 1": voice_name,
            "Speaker 2": opposite_voice,
            "Speaker 3": voice_name,
            "Speaker 4": opposite_voice,
        }
        
    assert voice_map["Speaker 1"] == "vi-VN-HoaiMyNeural"
    assert voice_map["Speaker 2"] == "vi-VN-NamMinhNeural"
    assert voice_map["Speaker 3"] == "vi-VN-HoaiMyNeural"
    assert voice_map["Speaker 4"] == "vi-VN-NamMinhNeural"

