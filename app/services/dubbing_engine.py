"""
Real AI Dubbing Engine
- ASR: OpenAI Whisper (local, free)
- Translation: deep-translator (Google Translate, free)
- TTS: edge-tts (Microsoft Edge TTS, free, high quality Vietnamese voices)
- Audio/Video: ffmpeg + pydub
"""
import os
import asyncio
import subprocess
import time

import json
import logging
import tempfile
from pathlib import Path

from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)


def extract_audio_from_video(video_path: str, audio_path: str) -> str:
    """Extract audio track from video file using ffmpeg"""
    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extract audio failed: {result.stderr[:500]}")
    logger.info(f"Extracted audio: {audio_path} ({os.path.getsize(audio_path)} bytes)")
    return audio_path


def transcribe_audio(audio_path: str, whisper_model: str = "base") -> list:
    """
    Transcribe audio using OpenAI Whisper (local model).
    Returns list of segments with start, end, text.
    """
    from app.utils.ffmpeg_utils import inject_ffmpeg_to_path
    inject_ffmpeg_to_path()
    
    import whisper
    import torch

    # Tự động dò tìm GPU để tăng tốc độ nhận dạng lên 10-20 lần
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Chuẩn hóa tên model (đảm bảo không bị hoa/thường)
    model_name = whisper_model.strip().lower() if whisper_model else "base"
    if model_name not in ["tiny", "base", "small", "medium", "large", "large-v1", "large-v2", "large-v3"]:
        model_name = "base"

    logger.info(f"Loading Whisper model ({model_name}) on device: {device}...")
    model = whisper.load_model(model_name, device=device)

    logger.info(f"Transcribing: {audio_path}")
    result = model.transcribe(audio_path, language=None, task="transcribe")

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
            "language": result.get("language", "en")
        })

    logger.info(f"Transcribed {len(segments)} segments, detected language: {result.get('language')} (device: {device})")
    return _merge_adjacent_segments(segments)

def _merge_adjacent_segments(segments: list, max_gap_ms: int = 250, max_duration: float = 5.0) -> list:
    """
    Gộp các phân đoạn kề nhau nếu khoảng cách nghỉ (gap) nhỏ hơn max_gap_ms
    và tổng thời lượng sau khi gộp không vượt quá max_duration.
    Giúp tạo thành các câu dài vừa phải, dịch thuật tự nhiên và tránh bị cắt cụt đuôi âm thanh.
    """
    if not segments:
        return []

    merged = []
    current = segments[0].copy()

    for next_seg in segments[1:]:
        gap = next_seg["start"] - current["end"]
        potential_duration = next_seg["end"] - current["start"]
        
        # Gộp nếu gap nhỏ và tổng thời lượng sau khi gộp không quá dài
        if gap <= (max_gap_ms / 1000.0) and potential_duration <= max_duration:
            current["end"] = next_seg["end"]
            current["text"] = (current["text"].strip() + " " + next_seg["text"].strip()).strip()
        else:
            merged.append(current)
            current = next_seg.copy()

    merged.append(current)
    logger.info(f"Gộp phân đoạn thoại thông minh (gap<{max_gap_ms}ms, max_dur<{max_duration}s): Giảm từ {len(segments)} xuống {len(merged)} phân đoạn.")
    return merged





def translate_segments(segments: list, target_lang: str = "vi", video_context: str = "neutral") -> list:
    """Translate each segment text to target language using Gemini API (if available) or Google Translate"""
    from app.config import settings

    # Sử dụng Gemini API nếu có API Key
    api_key = settings.GEMINI_API_KEY.strip()
    if api_key:
        logger.info(f"Sử dụng Gemini API với ngữ cảnh video: {video_context}...")
        try:
            from google import genai
            from google.genai import types
            import json
            import re

            client = genai.Client(api_key=api_key)

            # Tạo prompt dịch theo ngữ cảnh và tối ưu độ dài theo thời lượng nói
            # Vietnamese natural speech rate: ~3.5 syllables/second, each word ~1.7 syllables avg
            # Allow up to 3.6 words per second to avoid drop words (we can stretch tempo using ffmpeg up to 1.25x)
            prompt = (
                "You are an elite video dubbing translator (NOT subtitle translator).\n"
                f"The video context/topic is: {video_context}\n\n"
                "Translate the following video transcript segments into natural Vietnamese FOR VOICE DUBBING.\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "1. ACCURACY: Translation must convey the original meaning correctly and completely. Do not guess slang; translate to appropriate Vietnamese context.\n"
                "2. TIMING: Each translation must fit within the duration when spoken at a comfortable, natural pace.\n"
                "   - Target word count is specified for each segment dynamically based on original speech rate (comfortable upper limit).\n"
                "   - Speak naturally. Do NOT summarize too much or drop important words. The translation must be fully meaningful, natural, and complete.\n"
                "3. NATURAL SPEECH: Use spoken Vietnamese (not written/formal). It must sound like a real person talking naturally.\n"
                "4. OUTPUT: Return ONLY a JSON array of translated strings in the same order. No markdown, no explanation.\n"
                "   Example: [\"câu một\", \"câu hai\"]\n\n"
                "Segments to translate:\n"
            )
            for idx, seg in enumerate(segments):
                duration = seg.get("end", 0.0) - seg.get("start", 0.0)
                # Tính số từ câu tiếng Anh gốc
                orig_text = seg.get("text", "").strip()
                orig_words = len(orig_text.split()) if orig_text else 0
                
                # Tự động tính giới hạn từ Tiếng Việt (tiếng Việt thường dài hơn khoảng 25%)
                max_words = max(1, int(orig_words * 1.25))
                # Ràng buộc cận dưới: ít nhất bằng tốc độ 2.8 từ/giây để có đủ từ phát âm
                max_words = max(max_words, max(1, int(duration * 2.8)))
                # Ràng buộc cận trên: tối đa 3.8 từ/giây để tránh nói quá nhanh không khớp miệng
                max_words = min(max_words, max(1, int(duration * 3.8)))
                
                prompt += f"[{idx}] (Duration: {duration:.2f}s, target ~{max_words} Vietnamese words based on original speech rate): {orig_text}\n"

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            res_text = response.text.strip()

            # Tìm mảng JSON trong phản hồi của Gemini
            json_match = re.search(r'\[\s*".*"\s*\]', res_text, re.DOTALL) or re.search(r'\[.*\]', res_text, re.DOTALL)
            if json_match:
                translated_list = json.loads(json_match.group(0))
                if len(translated_list) == len(segments):

                    for idx, trans in enumerate(translated_list):
                        segments[idx]["translation"] = trans
                    logger.info(f"Đã dịch thành công {len(segments)} câu bằng Gemini API.")
                    return segments
            logger.warning("Không thể parse kết quả JSON của Gemini. Tiến hành fallback sang Google Translate.")
        except Exception as e:
            logger.warning(f"Lỗi khi dịch bằng Gemini API: {e}. Tiến hành fallback sang Google Translate.")

    # Fallback sang Google Translate
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="auto", target=target_lang)

    for seg in segments:
        try:
            if seg.get("language", "") == target_lang:
                # Already in target language, skip
                seg["translation"] = seg["text"]
            else:
                seg["translation"] = translator.translate(seg["text"])
        except Exception as e:
            logger.warning(f"Translation failed for segment: {e}")
            seg["translation"] = seg["text"]  # fallback to original

    logger.info(f"Translated {len(segments)} segments to {target_lang}")
    return segments



def _compress_translation(text: str, max_words: int) -> str:
    """
    Shorten Vietnamese translation to fit within max_words.
    Strategy: truncate long sentences at natural boundaries (comma/period).
    """
    words = text.split()
    if len(words) <= max_words:
        return text

    # Try to cut at a punctuation boundary within the limit
    truncated = words[:max_words]
    result = " ".join(truncated)
    # If last word ends without punctuation, add ellipsis to signal natural stop
    if not result.rstrip()[-1] in '.!?,;:':
        result = result.rstrip(',') + "..."
    logger.info(f"Compressed translation from {len(words)} to {len(truncated)} words")
    return result


def generate_ssml_for_segment(seg: dict, voice: str = "vi-VN-HoaiMyNeural",
                               video_context: str = "neutral") -> dict:
    """
    Generate timing-aware TTS parameters for a single dubbing segment.
    Returns a dict with 'text' and 'rate'.

    Strategy:
    - Natural Vietnamese speech: ~2.2 words/sec at normal rate
    - Keep rate at +0% by default; only speed up if words > 2.8 words/sec (still natural)
    - If translation still too long after rate boost, compress at sentence boundaries
    - NOTE: The merge step will do a final atempo stretch to lock audio to slot exactly
    """
    translation = seg.get("translation", seg.get("text", ""))
    start_time = seg.get("start", 0.0)
    end_time = seg.get("end", start_time + 3.0)
    duration = max(end_time - start_time, 0.5)  # at least 0.5s

    # Natural rate: 1.8 w/s; max comfortable rate before sounding rushed: 2.4 w/s
    max_words_normal = int(duration * 1.8)
    max_words_fast   = int(duration * 2.4)  # hard ceiling at fast rate

    # Adjust base rate from video context
    rate_map = {
        "fast": "+10%",
        "neutral": "+0%",
        "slow": "-5%",
        "teaching": "-8%",
    }
    rate = rate_map.get(video_context.lower(), "+0%")

    words = translation.split()
    word_count = len(words)

    # If words exceed normal rate, bump speed up to +15% before compressing
    if word_count > max_words_normal:
        rate = "+15%"

    # If words still exceed hard ceiling even at fast rate, compress to fit
    if word_count > max_words_fast and max_words_fast > 0:
        translation = _compress_translation(translation, max_words_fast)

    ssml_content = translation.strip()

    return {
        "text": ssml_content,
        "rate": rate
    }


def generate_tts_audio(text: str, output_path: str, voice: str = "vi-VN-HoaiMyNeural",
                        rate: str = "+0%") -> str:
    """
    Generate TTS audio using Microsoft Edge TTS (free) with retry logic.
    """
    # Edge TTS logic
    import edge_tts
    import asyncio
    import concurrent.futures
    import time

    async def _gen():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Xóa file cũ nếu có để đảm bảo tạo file mới hoàn toàn
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(asyncio.run, _gen()).result()
            except RuntimeError:
                asyncio.run(_gen())
                
            # Đảm bảo file được tạo thành công và có dung lượng hợp lệ (> 100 bytes)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return output_path
                
            raise ValueError("Sinh file TTS rỗng hoặc không tồn tại.")
        except Exception as e:
            logger.warning(f"Lần thử {attempt}/{max_retries} sinh TTS thất bại cho text '{text[:20]}...': {e}")
            if attempt < max_retries:
                time.sleep(1.0 * attempt)  # Backoff: 1s, 2s
            else:
                raise e

    return output_path


def select_voice(gender: str = "female", region: str = "south", engine: str = "edge") -> str:
    """Select appropriate voice based on selected engine and user preferences (Edge TTS fallback only)"""
    # Edge TTS voices (vi-VN-HoaiMyNeural for female, vi-VN-NamMinhNeural for male)
    voice_map = {
        ("female", "north"): "vi-VN-HoaiMyNeural",
        ("female", "south"): "vi-VN-HoaiMyNeural",
        ("female", "central"): "vi-VN-HoaiMyNeural",
        ("male", "north"): "vi-VN-NamMinhNeural",
        ("male", "south"): "vi-VN-NamMinhNeural",
        ("male", "central"): "vi-VN-NamMinhNeural",
    }
    return voice_map.get((gender.lower(), region.lower()), "vi-VN-HoaiMyNeural")



def generate_all_tts_segments(segments: list, audio_dir: str, job_id: str,
                               voice: str = "vi-VN-HoaiMyNeural",
                               video_context: str = "neutral") -> list:
    """
    Generate TTS audio for each translated segment using timing-aware SSML parameters.
    Processes segments in parallel to optimize processing speed for long videos.
    """
    import concurrent.futures

    # Giới hạn tối đa 3 luồng chạy song song để tránh bị Microsoft từ chối WebSocket
    max_workers = 3

    logger.info(f"Bắt đầu sinh TTS song song cho {len(segments)} segments sử dụng {max_workers} workers...")

    def process_single_segment(idx_seg_tuple):
        idx, seg = idx_seg_tuple
        output_path = os.path.join(audio_dir, f"{job_id}_seg_{idx}.mp3")
        try:
            translation = seg.get("translation", seg.get("text", ""))
            if not translation or not translation.strip():
                return idx, None

            # Generate timing-aware SSML configuration for this segment
            ssml_config = generate_ssml_for_segment(seg, voice=voice, video_context=video_context)
            seg["ssml_text"] = ssml_config["text"]
            seg["ssml_rate"] = ssml_config["rate"]

            # Generate TTS using parameters
            generate_tts_audio(
                text=ssml_config["text"],
                output_path=output_path,
                voice=voice,
                rate=ssml_config["rate"]
            )
            return idx, output_path

        except Exception as e:
            logger.error(f"TTS generation failed for segment {idx}: {e}")
            # Fallback to plain text TTS
            try:
                text = seg.get("translation", seg.get("text", ""))
                if text and text.strip():
                    generate_tts_audio(text, output_path, voice=voice)
                    return idx, output_path
            except Exception as e2:
                logger.error(f"Fallback TTS also failed for segment {idx}: {e2}")
            return idx, None

    # Sử dụng ThreadPoolExecutor để chạy song song
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        tasks = [(idx, seg) for idx, seg in enumerate(segments)]
        results = list(executor.map(process_single_segment, tasks))

    # Gán kết quả audio_path ngược lại segments
    for idx, audio_path in results:
        segments[idx]["audio_path"] = audio_path

    logger.info(f"Đã hoàn thành sinh TTS song song cho {len(segments)} segments.")
    return segments



def merge_tts_with_video(video_path: str, segments: list, bg_music_path: str,
                          output_video_path: str, output_audio_path: str,
                          keep_bg_music: bool = True,
                          bg_volume_db: int = -18) -> tuple:
    """
    Merge all TTS audio segments into a single audio track,
    then combine with the original video (replacing original audio).
    bg_volume_db: volume reduction in dB for original audio (0 = full, -40 = nearly silent).
    """
    from pydub import AudioSegment
    from app.utils.ffmpeg_utils import get_video_duration

    ffmpeg = get_ffmpeg_path()

    # Configure pydub to use our ffmpeg path
    AudioSegment.converter = ffmpeg
    try:
        from app.utils.ffmpeg_utils import get_ffprobe_path
        AudioSegment.ffprobe = get_ffprobe_path()
    except FileNotFoundError:
        pass  # pydub can work without ffprobe for basic operations

    # Get original video duration
    duration_secs = get_video_duration(video_path)
    video_duration_ms = int(duration_secs * 1000) if duration_secs > 0 else 60000
    logger.info(f"Video duration: {video_duration_ms}ms")

    # Create silent base track matching video duration
    mixed_audio = AudioSegment.silent(duration=video_duration_ms)

     # Overlay each TTS segment at its correct timestamp
    overlay_count = 0
    for idx, seg in enumerate(segments):
        if not seg.get("audio_path") or not os.path.exists(seg["audio_path"]):
            continue
        try:
            tts_audio = AudioSegment.from_file(seg["audio_path"])
            start_ms = int(seg["start"] * 1000)
            end_ms = int(seg["end"] * 1000)

            # --- TIMING SYNC: Lock TTS audio to original segment slot ---
            slot_duration = end_ms - start_ms  # exact slot from original transcript

            # Allow borrowing up to 0.8s from the gap to next segment
            # (so we don't cut off natural sentence endings)
            if idx < len(segments) - 1:
                next_start_ms = int(segments[idx + 1]["start"] * 1000)
            else:
                next_start_ms = video_duration_ms

            available_duration = slot_duration
            if next_start_ms > end_ms:
                gap = next_start_ms - end_ms
                available_duration += min(gap, 800)  # borrow at most 0.8s from gap

            tts_len = len(tts_audio)
            if tts_len > 0 and available_duration > 0:
                speed_ratio = tts_len / available_duration

                applied_ratio = 1.0
                if speed_ratio > 1.02:  # TTS is longer than available slot -> speed up
                    # Limit maximum speed stretch to 1.25x to preserve natural voice quality
                    applied_ratio = min(speed_ratio, 1.25)
                    logger.debug(f"Seg {idx}: stretched speed-up atempo={applied_ratio:.2f}x (original ratio was {speed_ratio:.2f}x)")
                elif speed_ratio < 0.95:  # TTS is shorter than available slot -> slow down to stretch
                    # Limit minimum speed stretch to 0.85x to preserve natural voice quality
                    applied_ratio = max(speed_ratio, 0.85)
                    logger.debug(f"Seg {idx}: stretched slow-down atempo={applied_ratio:.2f}x (original ratio was {speed_ratio:.2f}x)")

                if applied_ratio != 1.0:
                    filter_str = f"atempo={applied_ratio:.4f}"
                    temp_sped = seg["audio_path"].replace(".mp3", "_sync.mp3")
                    cmd_speed = [
                        ffmpeg, "-y", "-i", seg["audio_path"],
                        "-filter:a", filter_str,
                        temp_sped
                    ]
                    result_speed = subprocess.run(cmd_speed, capture_output=True)
                    if result_speed.returncode == 0 and os.path.exists(temp_sped):
                        tts_audio = AudioSegment.from_file(temp_sped)
                        os.remove(temp_sped)

                # Final trim with Fade Out to prevent sudden clicks or unnatural cuts
                max_allowed_ms = available_duration
                if len(tts_audio) > max_allowed_ms:
                    fade_duration = min(150, max_allowed_ms)
                    tts_audio = tts_audio[:max_allowed_ms].fade_out(fade_duration)

            mixed_audio = mixed_audio.overlay(tts_audio, position=start_ms)
            overlay_count += 1
        except Exception as e:
            logger.warning(f"Failed to overlay segment at {seg.get('start', '?')}s: {e}")

    logger.info(f"Overlaid {overlay_count}/{len(segments)} TTS segments onto audio track")

    # If keeping background music, try to extract and mix it from original
    if keep_bg_music:
        try:
            # Extract original audio from video
            temp_orig_audio = output_audio_path.replace(".mp3", "_orig_temp.wav")
            cmd_extract = [
                ffmpeg, "-y", "-i", video_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                temp_orig_audio
            ]
            subprocess.run(cmd_extract, capture_output=True)

            if os.path.exists(temp_orig_audio):
                orig_audio = AudioSegment.from_file(temp_orig_audio)
                # Apply user-configured volume reduction (default -18dB)
                # Clamp to safe range: 0dB (full) to -40dB (nearly silent)
                volume_reduction = max(-40, min(0, bg_volume_db))
                orig_audio = orig_audio + volume_reduction  # pydub uses + to add dB offset
                # Trim or extend to match video duration
                orig_audio = orig_audio[:video_duration_ms]
                mixed_audio = mixed_audio.overlay(orig_audio)
                os.remove(temp_orig_audio)
                logger.info(f"Mixed original audio as background at {volume_reduction}dB")
        except Exception as e:
            logger.warning(f"Failed to mix background audio: {e}")

    # Export mixed audio to temp WAV
    temp_audio = output_audio_path.replace(".mp3", "_temp.wav")
    mixed_audio.export(temp_audio, format="wav")
    logger.info(f"Mixed audio track created: {temp_audio}")

    # Combine video + new audio using ffmpeg
    cmd_video = [
        ffmpeg, "-y",
        "-i", video_path,        # Original video (for video stream)
        "-i", temp_audio,        # New dubbed audio
        "-c:v", "copy",          # Copy video stream as-is (fast, no re-encode)
        "-c:a", "aac",           # Encode audio as AAC
        "-b:a", "192k",
        "-map", "0:v:0",         # Use video from first input
        "-map", "1:a:0",         # Use audio from second input
        "-shortest",
        output_video_path
    ]
    result = subprocess.run(cmd_video, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"ffmpeg merge failed: {result.stderr[:500]}")
        # Fallback: just copy original video
        import shutil
        shutil.copy(video_path, output_video_path)
        logger.warning("Fallback: copied original video as output")

    # Export final audio as MP3
    try:
        mixed_audio.export(output_audio_path, format="mp3", bitrate="192k")
    except Exception:
        cmd_mp3 = [
            ffmpeg, "-y", "-i", temp_audio, "-b:a", "192k", output_audio_path
        ]
        subprocess.run(cmd_mp3, capture_output=True)

    # Cleanup temp file
    if os.path.exists(temp_audio):
        os.remove(temp_audio)

    logger.info(f"Final dubbed video: {output_video_path} ({os.path.getsize(output_video_path)} bytes)")
    return output_video_path, output_audio_path


def generate_srt_file(segments: list, output_path: str) -> str:
    """Generate SRT subtitle file from translated segments"""
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            start = _seconds_to_srt_time(seg["start"])
            end = _seconds_to_srt_time(seg["end"])
            text = seg.get("translation", seg.get("text", ""))
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
    return output_path


def generate_vtt_file(segments: list, output_path: str) -> str:
    """Generate WebVTT subtitle file from translated segments"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for idx, seg in enumerate(segments, 1):
            start = _seconds_to_vtt_time(seg["start"])
            end = _seconds_to_vtt_time(seg["end"])
            text = seg.get("translation", seg.get("text", ""))
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
    return output_path


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _seconds_to_vtt_time(seconds: float) -> str:
    """Convert seconds to WebVTT timestamp format (HH:MM:SS.mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
