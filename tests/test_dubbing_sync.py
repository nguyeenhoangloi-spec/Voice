import os
import pytest
import shutil
import tempfile
from pydub import AudioSegment
from app.services.dubbing_engine import (
    preprocess_text_for_tts,
    generate_ssml_for_segment,
    _adjust_audio_speed,
    merge_tts_with_video
)
from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path

def test_preprocess_text_for_tts():
    # Test currency conversion
    assert "một trăm đô la" in preprocess_text_for_tts("$100")
    assert "năm mươi đô la Mỹ" in preprocess_text_for_tts("50 USD")
    assert "mười nghìn đồng" in preprocess_text_for_tts("10000 VND")

    # Test percentages
    assert "hai mươi phần trăm" in preprocess_text_for_tts("20%")

    # Test numbers conversion
    assert "hai nghìn không trăm hai mươi sáu" in preprocess_text_for_tts("2026")
    assert "mười lăm" in preprocess_text_for_tts("15")

    # Test special characters replacement
    assert "và" in preprocess_text_for_tts("A & B")
    assert "a còng" in preprocess_text_for_tts("user@domain")
    assert "thăng" in preprocess_text_for_tts("#1")
    assert preprocess_text_for_tts("#1") == "thăng một"

def test_generate_ssml_for_segment_timing():
    # Câu ngắn bình thường, wps <= 2.8 -> speed rate = 0%
    seg_normal = {
        "start": 0.0,
        "end": 3.0,
        "translation": "Chào bạn"
    }
    config = generate_ssml_for_segment(seg_normal, voice="vi-VN-HoaiMyNeural", video_context="neutral")
    assert config["rate"] == "+0%"

    # Câu siêu dài, wps > 2.8 -> speed rate tự động tăng
    seg_long = {
        "start": 0.0,
        "end": 2.0,
        "translation": "Hôm nay tôi sẽ hướng dẫn các bạn cách để cài đặt một hệ thống trí tuệ nhân tạo lồng tiếng tự động cực kỳ nhanh chóng và đơn giản"
    }
    config_long = generate_ssml_for_segment(seg_long, voice="vi-VN-HoaiMyNeural", video_context="neutral")
    # Phải có dấu '+' và rate lớn hơn 0%
    rate_val = int(config_long["rate"].replace("+", "").replace("%", ""))
    assert rate_val > 0
    # Không được vượt quá giới hạn an toàn +60% của Edge TTS
    assert rate_val <= 60

def test_adjust_audio_speed():
    # Tạo một thư mục tạm để lưu file test
    temp_dir = tempfile.mkdtemp()
    test_audio_path = os.path.join(temp_dir, "test_speed.wav")
    
    try:
        # Cấu hình pydub
        AudioSegment.converter = get_ffmpeg_path()
        # Tạo file audio silent dài 2 giây (2000 ms)
        silent_audio = AudioSegment.silent(duration=2000)
        silent_audio.export(test_audio_path, format="wav")
        
        # Tăng tốc độ lên 1.5x
        adjusted_path = _adjust_audio_speed(test_audio_path, 1.5)
        
        # Đọc lại và kiểm tra độ dài mới (khoảng 2000 / 1.5 = 1333 ms)
        new_audio = AudioSegment.from_file(adjusted_path)
        new_duration_ms = len(new_audio)
        
        # Cho phép sai số nhỏ do nén/xuất của FFmpeg
        assert 1200 <= new_duration_ms <= 1450
        
    finally:
        # Dọn dẹp file tạm
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def test_merge_tts_with_video_timing():
    temp_dir = tempfile.mkdtemp()
    
    # Paths cho test
    video_path = os.path.join(temp_dir, "input_video.mp4")
    bg_music_path = os.path.join(temp_dir, "bg_music.wav")
    output_video_path = os.path.join(temp_dir, "output_video.mp4")
    output_audio_path = os.path.join(temp_dir, "output_audio.mp3")
    
    try:
        ffmpeg = get_ffmpeg_path()
        AudioSegment.converter = ffmpeg
        
        # 1. Tạo video giả lập (10 giây) để test merge
        # Tạo file audio silent dài 10 giây
        AudioSegment.silent(duration=10000).export(bg_music_path, format="wav")
        
        # Dùng ffmpeg sinh video test dài 10s
        cmd_gen_video = [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=10",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-t", "10",
            video_path
        ]
        import subprocess
        subprocess.run(cmd_gen_video, capture_output=True, check=True)
        
        # 2. Tạo câu thoại giả lập
        # Phân đoạn 1: 1.0s đến 3.0s (câu thoại 1s, vừa khít slot)
        seg1_audio = os.path.join(temp_dir, "seg1.mp3")
        AudioSegment.silent(duration=1000).export(seg1_audio, format="mp3")
        
        # Phân đoạn 2: 4.0s đến 6.0s (câu thoại dài 3s, dài hơn slot -> hệ thống phải nén atempo / trim)
        seg2_audio = os.path.join(temp_dir, "seg2.mp3")
        AudioSegment.silent(duration=3000).export(seg2_audio, format="mp3")
        
        segments = [
            {
                "start": 1.0,
                "end": 3.0,
                "text": "Hello world",
                "translation": "Xin chào thế giới",
                "audio_path": seg1_audio
            },
            {
                "start": 4.0,
                "end": 6.0,
                "text": "This is a very long segment that is longer than the original time slot allocated to it",
                "translation": "Đây là một câu thoại rất dài và nó vượt quá thời lượng cho phép của cảnh này",
                "audio_path": seg2_audio
            }
        ]
        
        # 3. Tiến hành merge
        out_v, out_a = merge_tts_with_video(
            video_path=video_path,
            segments=segments,
            bg_music_path=bg_music_path,
            output_video_path=output_video_path,
            output_audio_path=output_audio_path,
            keep_bg_music=False
        )
        
        # 4. Kiểm tra đầu ra
        assert os.path.exists(out_v)
        assert os.path.exists(out_a)
        assert os.path.getsize(out_v) > 1000
        assert os.path.getsize(out_a) > 1000
        
        # Đọc thời lượng video xuất ra
        from app.utils.ffmpeg_utils import get_video_duration
        duration = get_video_duration(out_v)
        # Thời lượng video xuất ra phải chính xác 10s (bằng video gốc)
        assert 9.8 <= duration <= 10.2
        
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
