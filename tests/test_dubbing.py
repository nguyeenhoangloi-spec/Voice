import pytest
from unittest.mock import patch, MagicMock
from fastapi import status

@pytest.fixture
def logged_in_client(client):
    # Đăng ký và Đăng nhập để lấy cookie session
    client.post(
        "/auth/register",
        data={"email": "test@voiceai.com", "password": "securepassword", "full_name": "Test User"}
    )
    client.post(
        "/auth/login",
        data={"email": "test@voiceai.com", "password": "securepassword"}
    )
    return client

def test_check_link_unsafe(logged_in_client):
    # Gửi URL local nhạy cảm (SSRF attack vector)
    response = logged_in_client.post(
        "/dubbing/check-link",
        json={"url": "http://127.0.0.1:8000/admin"}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["success"] is False
    assert "bị cấm" in response.json()["error"]

@patch("app.services.link_adapters.youtube.YouTubeAdapter.extract_metadata")
def test_check_link_youtube_success(mock_extract, logged_in_client):
    # Mock kết quả trích xuất metadata
    mock_extract.return_value = {
        "success": True,
        "title": "Mock Video Title",
        "duration": 212.0,
        "author": "Mock Author",
        "thumbnail": "https://example.com/thumb.jpg",
        "youtube_id": "dQw4w9WgXcQ"
    }

    # Test link Youtube hợp lệ
    response = logged_in_client.post(
        "/dubbing/check-link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True
    assert "dQw4w9WgXcQ" in response.json()["data"]["youtube_id"]

@patch("app.routers.dubbing.probe_media_file")
def test_upload_media_success(mock_probe, logged_in_client):
    # Mock kết quả probe của ffprobe
    mock_probe.return_value = {
        "success": True,
        "duration": 45.5,
        "file_size": 2048,
        "has_audio": True,
        "has_video": True,
        "format_name": "mp4"
    }

    # Upload file giả lập
    file_payload = {"file": ("test.mp4", b"fake-mp4-binary-content", "video/mp4")}
    response = logged_in_client.post(
        "/dubbing/upload",
        files=file_payload
    )
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True
    assert response.json()["duration"] == 45.5

def test_create_job_and_fetch_status(logged_in_client):
    # Tạo job mới
    create_payload = {
        "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "source_type": "link",
        "title": "Never Gonna Give You Up",
        "duration": 212.0,
        "voice_gender": "female",
        "voice_region": "south",
        "voice_emotion": "happy",
        "keep_bg_music": True,
        "generate_subtitles": True,
        "translation_mode": "vietnamese"
    }
    
    create_resp = logged_in_client.post(
        "/dubbing/create",
        json=create_payload
    )
    assert create_resp.status_code == status.HTTP_200_OK
    assert create_resp.json()["success"] is True
    job_id = create_resp.json()["job_id"]
    
    # Lấy thông tin status của job vừa tạo
    status_resp = logged_in_client.get(f"/dubbing/job/{job_id}/status")
    assert status_resp.status_code == status.HTTP_200_OK
    data = status_resp.json()
    assert data["job_id"] == job_id
    assert len(data["steps"]) == 20
    assert data["steps"][0]["name"] == "Kiểm tra liên kết"
