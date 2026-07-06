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


def preprocess_text_for_tts(text: str) -> str:
    """
    Normalize text before feeding to TTS to improve pronunciation accuracy.
    Handles: numbers, currency, units, special characters, foreign proper nouns.
    """
    import re

    if not text or not text.strip():
        return text

    # --- Currency ---
    text = re.sub(r'\$(\d[\d,\.]*)', lambda m: _num_to_viet(m.group(1).replace(',','').replace('.','')) + ' đô la', text)
    text = re.sub(r'(\d[\d,\.]*)\s*USD', lambda m: _num_to_viet(m.group(1).replace(',','').replace('.','')) + ' đô la Mỹ', text)
    text = re.sub(r'(\d[\d,\.]*)\s*VND', lambda m: _num_to_viet(m.group(1).replace(',','').replace('.','')) + ' đồng', text)

    # --- Percentages ---
    text = re.sub(r'(\d+)%', lambda m: _num_to_viet(m.group(1)) + ' phần trăm', text)

    # --- Large standalone numbers (4+ digits) ---
    text = re.sub(r'\b(\d{4,})\b', lambda m: _num_to_viet(m.group(1)), text)

    # --- Small numbers (1-3 digits) standalone ---
    text = re.sub(r'\b(\d{1,3})\b', lambda m: _num_to_viet(m.group(1)), text)

    # --- Special symbols ---
    text = text.replace('&', ' và ')
    text = text.replace('@', ' a còng ')
    text = text.replace('#', ' thăng ')
    text = text.replace('+', ' cộng ')
    text = text.replace('=', ' bằng ')
    text = text.replace('>', ' lớn hơn ')
    text = text.replace('<', ' nhỏ hơn ')
    text = text.replace('...', ' ')
    text = text.replace('—', ', ')
    text = text.replace('–', ', ')

    # --- Clean up extra spaces ---
    text = re.sub(r' +', ' ', text).strip()
    return text


def _num_to_viet(num_str: str) -> str:
    """Convert a numeric string to Vietnamese words."""
    try:
        # Remove commas and leading zeros
        num_str = num_str.replace(',', '').replace(' ', '')
        # Handle decimal numbers
        if '.' in num_str:
            parts = num_str.split('.')
            int_part = _int_to_viet(int(parts[0]))
            dec_part = ' phẩy ' + ' '.join(_int_to_viet(int(d)) for d in parts[1])
            return int_part + dec_part
        return _int_to_viet(int(num_str))
    except (ValueError, OverflowError):
        return num_str  # fallback: keep original if conversion fails


def _int_to_viet(n: int) -> str:
    """Recursively convert integer to Vietnamese words."""
    if n < 0:
        return 'âm ' + _int_to_viet(-n)
    ones = ['không','một','hai','ba','bốn','năm','sáu','bảy','tám','chín']
    tens = ['','mười','hai mươi','ba mươi','bốn mươi','năm mươi',
            'sáu mươi','bảy mươi','tám mươi','chín mươi']
    if n < 10:
        return ones[n]
    if n < 100:
        t = tens[n // 10]
        o = ones[n % 10]
        if n % 10 == 0:
            return t
        if n % 10 == 1 and n > 10:
            return t + ' mốt'
        if n % 10 == 5 and n > 10:
            return t + ' lăm'
        return t + ' ' + o
    if n < 1000:
        h = ones[n // 100] + ' trăm'
        r = n % 100
        if r == 0:
            return h
        if r < 10:
            return h + ' lẻ ' + ones[r]
        return h + ' ' + _int_to_viet(r)
    if n < 1_000_000:
        th = _int_to_viet(n // 1000) + ' nghìn'
        r = n % 1000
        if r == 0:
            return th
        if r < 100:
            return th + ' không trăm ' + _int_to_viet(r)
        return th + ' ' + _int_to_viet(r)
    if n < 1_000_000_000:
        m = _int_to_viet(n // 1_000_000) + ' triệu'
        r = n % 1_000_000
        if r == 0:
            return m
        return m + ' ' + _int_to_viet(r)
    b = _int_to_viet(n // 1_000_000_000) + ' tỷ'
    r = n % 1_000_000_000
    if r == 0:
        return b
    return b + ' ' + _int_to_viet(r)


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
    Returns list of segments with start, end, text, speaker.
    Uses word_timestamps for more accurate timing.
    Speaker changes are detected via silence gaps > 1.5s.
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

    logger.info(f"Transcribing with word_timestamps: {audio_path}")
    # word_timestamps=True gives per-word timing for much more accurate sync
    result = model.transcribe(
        audio_path,
        language=None,
        task="transcribe",
        word_timestamps=True,
    )

    segments = []
    for seg in result.get("segments", []):
        # Use word-level start/end if available for tighter timing
        words = seg.get("words", [])
        if words:
            seg_start = round(words[0]["start"], 3)
            seg_end   = round(words[-1]["end"], 3)
        else:
            seg_start = round(seg["start"], 2)
            seg_end   = round(seg["end"], 2)

        segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": seg["text"].strip(),
            "language": result.get("language", "en"),
            "speaker": "Speaker 1",  # will be updated by speaker detection
        })

    # Simple speaker change detection based on silence gaps
    segments = _detect_speaker_changes(segments)

    logger.info(f"Transcribed {len(segments)} segments, detected language: {result.get('language')} (device: {device})")
    return _merge_adjacent_segments(segments)


def _detect_speaker_changes(segments: list, silence_threshold: float = 1.5) -> list:
    """
    Heuristic speaker change detection based on silence gaps.
    Gap > silence_threshold seconds → likely a different speaker.
    Alternates between Speaker 1 and Speaker 2 on each change.
    """
    if not segments:
        return segments

    current_speaker = "Speaker 1"
    speaker_switch = {"Speaker 1": "Speaker 2", "Speaker 2": "Speaker 1"}

    segments[0]["speaker"] = current_speaker
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i - 1]["end"]
        if gap >= silence_threshold:
            current_speaker = speaker_switch[current_speaker]
            logger.debug(f"Speaker change at {segments[i]['start']:.2f}s (gap={gap:.2f}s) → {current_speaker}")
        segments[i]["speaker"] = current_speaker

    speakers_found = set(s["speaker"] for s in segments)
    logger.info(f"Speaker detection: found {len(speakers_found)} speaker(s): {speakers_found}")
    return segments

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
                "You are an elite Vietnamese video dubbing translator with 20+ years of experience.\n"
                f"Video topic/context: {video_context}\n\n"
                "YOUR TASK: Translate English video transcript segments into natural spoken Vietnamese for voice dubbing.\n\n"
                "STRICT RULES:\n"
                "1. PROPER NOUNS: Keep names of people, brands, products, places UNCHANGED.\n"
                "   - 'John said' → 'John nói' (NOT 'Giăng nói')\n"
                "   - 'iPhone 16' → 'iPhone 16' (never translate product/brand names)\n"
                "2. TECHNICAL TERMS: Keep English terms when no natural Vietnamese equivalent exists.\n"
                "   - 'API', 'machine learning', 'server' → keep as-is or use widely accepted Vietnamese equivalent\n"
                "3. NATURAL SPEECH: Use conversational Vietnamese, never formal/written style.\n"
                "   - Mirror the speaker's tone (casual, excited, serious) from the original.\n"
                "4. COMPLETENESS: Translate the full meaning. Never drop important information.\n"
                "5. CONTEXT: [PREV] shows the previous line for context only. Translate only [CURR].\n"
                "6. TIMING: ~word count shown per segment. Approximate it but never sacrifice meaning.\n"
                "7. OUTPUT: Return ONLY a JSON array of strings in the same order. No markdown.\n"
                "   Example: [\"c\u00e2u m\u1ed9t\", \"c\u00e2u hai\"]\n\n"
                "Segments:\n"
            )
            for idx, seg in enumerate(segments):
                duration = seg.get("end", 0.0) - seg.get("start", 0.0)
                orig_text = seg.get("text", "").strip()
                orig_words = len(orig_text.split()) if orig_text else 0

                # Target word count for Vietnamese (25% longer than English)
                max_words = max(1, int(orig_words * 1.25))
                max_words = max(max_words, max(1, int(duration * 2.8)))
                max_words = min(max_words, max(1, int(duration * 3.8)))

                # Include previous segment as context clue
                prev_text = segments[idx - 1].get("text", "").strip() if idx > 0 else ""

                if prev_text:
                    prompt += f"[{idx}] (~{max_words} words, {duration:.1f}s)\n  [PREV]: {prev_text}\n  [CURR]: {orig_text}\n\n"
                else:
                    prompt += f"[{idx}] (~{max_words} words, {duration:.1f}s)\n  [CURR]: {orig_text}\n\n"

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
    - Natural Vietnamese speech: ~3.2 words/sec at normal rate
    - Keep rate at +0% by default; only speed up if words > 3.5 words/sec (still natural)
    - If translation still too long after rate boost, compress at sentence boundaries
    - NOTE: The merge step will do a final atempo stretch to lock audio to slot exactly
    """
    translation = seg.get("translation", seg.get("text", ""))
    start_time = seg.get("start", 0.0)
    end_time = seg.get("end", start_time + 3.0)
    duration = max(end_time - start_time, 0.5)  # at least 0.5s

    # Natural rate: 3.0 w/s; max comfortable rate before sounding rushed: 4.0 w/s
    # Vietnamese speech research: ~3.2-3.8 words/sec is natural and clear
    max_words_normal = int(duration * 3.0)   # normal reading pace
    max_words_fast   = int(duration * 4.5)   # hard ceiling - only compress beyond this

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

    # Only compress if words exceed the hard ceiling (4.5 w/s) - prevents cutting important words
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



# Default multi-speaker voice map (auto-assigned based on detected speakers)
DEFAULT_SPEAKER_VOICE_MAP = {
    "Speaker 1": "vi-VN-HoaiMyNeural",   # female voice for speaker 1
    "Speaker 2": "vi-VN-NamMinhNeural",   # male voice for speaker 2
    "Speaker 3": "vi-VN-HoaiMyNeural",   # female again for 3rd speaker
    "Speaker 4": "vi-VN-NamMinhNeural",
}


def generate_all_tts_segments(segments: list, audio_dir: str, job_id: str,
                               voice: str = "vi-VN-HoaiMyNeural",
                               video_context: str = "neutral",
                               voice_map: dict = None) -> list:
    """
    Generate TTS audio for each translated segment using timing-aware SSML parameters.
    Supports multi-speaker: each segment can use a different voice based on its 'speaker' field.
    Processes segments in parallel to optimize processing speed for long videos.
    """
    import concurrent.futures

    # Build effective voice map
    # If only 1 unique speaker detected, use the single chosen voice for all
    speakers = set(s.get("speaker", "Speaker 1") for s in segments)
    if len(speakers) <= 1:
        effective_voice_map = {spk: voice for spk in speakers}
        logger.info(f"Single speaker detected → using voice: {voice}")
    else:
        # Multi-speaker: use provided voice_map or default alternating map
        effective_voice_map = voice_map or DEFAULT_SPEAKER_VOICE_MAP
        logger.info(f"Multi-speaker detected ({len(speakers)} speakers) → voice map: {effective_voice_map}")

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

            # Preprocess text to improve pronunciation (numbers, symbols, etc.)
            cleaned_text = preprocess_text_for_tts(translation)

            # Determine voice for this segment's speaker
            speaker = seg.get("speaker", "Speaker 1")
            seg_voice = effective_voice_map.get(speaker, voice)

            # Generate timing-aware SSML configuration for this segment
            ssml_config = generate_ssml_for_segment(seg, voice=seg_voice, video_context=video_context)
            # Use preprocessed text in place of raw translation
            final_text = preprocess_text_for_tts(ssml_config["text"])
            # Ensure text ends with punctuation so Edge TTS completes the last word naturally
            if final_text and final_text[-1] not in '.!?,;:…':
                final_text += '.'
            ssml_config["text"] = final_text
            seg["ssml_text"] = final_text
            seg["ssml_rate"] = ssml_config["rate"]
            seg["voice_used"] = seg_voice

            # Generate TTS using parameters
            generate_tts_audio(
                text=ssml_config["text"],
                output_path=output_path,
                voice=seg_voice,
                rate=ssml_config["rate"]
            )

            # ─── CHECK: Log actual audio length vs slot (no action, just info) ─
            slot_ms = max(0, (seg.get("end", 0) - seg.get("start", 0)) * 1000)
            if os.path.exists(output_path):
                from pydub import AudioSegment as _AS
                _AS.converter = get_ffmpeg_path()
                try:
                    _AS.ffprobe = get_ffprobe_path()
                except Exception:
                    pass
                try:
                    actual_ms = len(_AS.from_file(output_path))
                    if actual_ms > slot_ms * 1.2:
                        logger.info(f"Seg {idx}: audio={actual_ms:.0f}ms, slot={slot_ms:.0f}ms (will overlap slightly - OK)")
                except Exception as _e:
                    logger.warning(f"Seg {idx}: smart retry check FAILED ({type(_e).__name__}: {_e})")
            # ───────────────────────────────────────────────────────────────


            return idx, output_path

        except Exception as e:
            logger.error(f"TTS generation failed for segment {idx}: {e}")
            # Fallback to plain text TTS
            try:
                text = preprocess_text_for_tts(seg.get("translation", seg.get("text", "")))
                if text and text.strip():
                    seg_voice = effective_voice_map.get(seg.get("speaker", "Speaker 1"), voice)
                    generate_tts_audio(text, output_path, voice=seg_voice)
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

    # Create silent base track slightly longer than video to prevent last segment cutoff
    # (extra 5s buffer - will be trimmed back to video_duration_ms after all overlays)
    mixed_audio = AudioSegment.silent(duration=video_duration_ms + 5000)

     # Overlay each TTS segment at its correct timestamp
    overlay_count = 0
    for idx, seg in enumerate(segments):
        if not seg.get("audio_path") or not os.path.exists(seg["audio_path"]):
            continue
        try:
            tts_audio = AudioSegment.from_file(seg["audio_path"])
            start_ms = int(seg["start"] * 1000)
            end_ms = int(seg["end"] * 1000)

            # Fade-in 50ms to prevent click noise at segment start
            if len(tts_audio) > 100:
                tts_audio = tts_audio.fade_in(50)

            # NO trimming - let the audio play fully to avoid dropping words
            # If it slightly overlaps with next segment, pydub overlay will mix them

            mixed_audio = mixed_audio.overlay(tts_audio, position=start_ms)
            overlay_count += 1
        except Exception as e:
            logger.warning(f"Failed to overlay segment at {seg.get('start', '?')}s: {e}")

    logger.info(f"Overlaid {overlay_count}/{len(segments)} TTS segments onto audio track")

    # Trim back to exact video duration (last segment may have run slightly over)
    mixed_audio = mixed_audio[:video_duration_ms]

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
