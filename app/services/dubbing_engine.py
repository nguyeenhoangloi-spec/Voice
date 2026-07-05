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


def transcribe_audio(audio_path: str) -> list:
    """
    Transcribe audio using OpenAI Whisper (local model).
    Returns list of segments with start, end, text.
    """
    import whisper

    logger.info("Loading Whisper model (base)...")
    model = whisper.load_model("base")

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

    logger.info(f"Transcribed {len(segments)} segments, detected language: {result.get('language')}")
    return segments


def translate_segments(segments: list, target_lang: str = "vi") -> list:
    """Translate each segment text to target language using Google Translate"""
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
    Generate timing-aware SSML parameters for a single dubbing segment.
    Returns a dict with 'text' (containing break tags) and 'rate' (e.g. '+10%').

    Rules:
    - Vietnamese natural speech: 2.0-3.2 words/sec
    - If translation too long: compress to fit duration
    - If translation too short: add <break> tags at punctuation
    - Prosody rate based on video context (neutral/fast/slow)
    """
    translation = seg.get("translation", seg.get("text", ""))
    start_time = seg.get("start", 0.0)
    end_time = seg.get("end", start_time + 3.0)
    duration = end_time - start_time

    # Word count limits based on natural Vietnamese speaking rate
    max_words = int(duration * 3.2)

    # Adjust prosody rate based on video context
    rate_map = {
        "fast": "+10%",
        "neutral": "+0%",
        "slow": "-5%",
        "teaching": "-8%",
    }
    rate = rate_map.get(video_context.lower(), "+0%")

    # Compress if too long
    words = translation.split()
    if len(words) > max_words and max_words > 0:
        translation = _compress_translation(translation, max_words)

    # Use clean translation (Edge TTS naturally pauses on punctuation like commas, periods, and ellipsis)
    ssml_content = translation.strip()

    # If very short duration but translation is long, increase rate to squeeze in
    current_word_count = len(ssml_content.split())
    if duration > 0 and current_word_count / duration > 3.5:
        rate = "+15%"  # speak faster to fit

    return {
        "text": ssml_content,
        "rate": rate
    }


def generate_tts_audio(text: str, output_path: str, voice: str = "vi-VN-HoaiMyNeural",
                        rate: str = "+0%") -> str:
    """
    Generate Vietnamese TTS audio using Microsoft Edge TTS (free, high quality).
    Parameters:
    - text: text to synthesize (can contain break tags like <break time="200ms"/>)
    - voice: voice name
    - rate: speed modification rate (e.g. "+10%", "-5%", "+0%")
    """
    import edge_tts

    async def _generate():
        # Pass break tags directly inside text parameter, and rate as constructor argument.
        # Edge-TTS will wrap it in correct SSML tags internally without double escaping.
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)

    # Run async TTS generation (handle both sync and async contexts)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _generate()).result()
        else:
            loop.run_until_complete(_generate())
    except RuntimeError:
        asyncio.run(_generate())

    logger.info(f"Generated TTS: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path


def select_voice(gender: str = "female", region: str = "south") -> str:
    """Select appropriate Vietnamese voice based on user preferences"""
    voice_map = {
        ("female", "north"): "vi-VN-HoaiMyNeural",
        ("female", "south"): "vi-VN-HoaiMyNeural",
        ("male", "north"): "vi-VN-NamMinhNeural",
        ("male", "south"): "vi-VN-NamMinhNeural",
    }
    key = (gender.lower(), region.lower())
    return voice_map.get(key, "vi-VN-HoaiMyNeural")


def generate_all_tts_segments(segments: list, audio_dir: str, job_id: str,
                               voice: str = "vi-VN-HoaiMyNeural",
                               video_context: str = "neutral") -> list:
    """
    Generate TTS audio for each translated segment using timing-aware SSML parameters.
    """
    for idx, seg in enumerate(segments):
        output_path = os.path.join(audio_dir, f"{job_id}_seg_{idx}.mp3")
        try:
            translation = seg.get("translation", seg.get("text", ""))
            if not translation or not translation.strip():
                seg["audio_path"] = None
                continue

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
            seg["audio_path"] = output_path

        except Exception as e:
            logger.error(f"TTS generation failed for segment {idx}: {e}")
            # Fallback to plain text TTS
            try:
                text = seg.get("translation", seg.get("text", ""))
                if text and text.strip():
                    generate_tts_audio(text, output_path, voice=voice)
                    seg["audio_path"] = output_path
                else:
                    seg["audio_path"] = None
            except Exception as e2:
                logger.error(f"Fallback TTS also failed for segment {idx}: {e2}")
                seg["audio_path"] = None

    return segments


def merge_tts_with_video(video_path: str, segments: list, bg_music_path: str,
                          output_video_path: str, output_audio_path: str,
                          keep_bg_music: bool = True) -> tuple:
    """
    Merge all TTS audio segments into a single audio track,
    then combine with the original video (replacing original audio).
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
    for seg in segments:
        if not seg.get("audio_path") or not os.path.exists(seg["audio_path"]):
            continue
        try:
            tts_audio = AudioSegment.from_file(seg["audio_path"])
            start_ms = int(seg["start"] * 1000)

            # Calculate available time slot
            end_ms = int(seg["end"] * 1000)
            slot_duration = end_ms - start_ms

            # Speed up TTS if it's much longer than the slot
            if len(tts_audio) > 0 and slot_duration > 0:
                speed_ratio = len(tts_audio) / slot_duration
                if speed_ratio > 1.5:
                    # Speed up using ffmpeg atempo filter
                    tempo = min(speed_ratio, 2.0)
                    temp_sped = seg["audio_path"].replace(".mp3", "_sped.mp3")
                    cmd_speed = [
                        ffmpeg, "-y", "-i", seg["audio_path"],
                        "-filter:a", f"atempo={tempo}",
                        temp_sped
                    ]
                    subprocess.run(cmd_speed, capture_output=True)
                    if os.path.exists(temp_sped):
                        tts_audio = AudioSegment.from_file(temp_sped)
                        os.remove(temp_sped)

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
                # Reduce original audio volume to -18dB so TTS is dominant
                orig_audio = orig_audio - 18
                # Trim or extend to match video duration
                orig_audio = orig_audio[:video_duration_ms]
                mixed_audio = mixed_audio.overlay(orig_audio)
                os.remove(temp_orig_audio)
                logger.info("Mixed original audio as background at -18dB")
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
