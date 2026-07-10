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
import re

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


def parse_vtt_time(time_str: str) -> float:
    """Parse WebVTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) into seconds"""
    try:
        time_str = time_str.strip()
        parts = time_str.split(':')
        if len(parts) == 2:
            m, s = parts
            h = 0.0
        else:
            h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception:
        return 0.0


def download_youtube_subtitles(url: str, job_id: str) -> list:
    """
    Download English subtitles from YouTube URL using yt-dlp.
    Returns list of segments with start, end, text, speaker.
    """
    import subprocess
    import glob
    import re
    from app.utils.ffmpeg_utils import inject_ffmpeg_to_path
    inject_ffmpeg_to_path()

    temp_sub_prefix = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "temp", f"sub_{job_id}")
    os.makedirs(os.path.dirname(temp_sub_prefix), exist_ok=True)

    logger.info(f"Downloading YouTube subtitles for: {url}")
    # Run yt-dlp to download subtitles (prefer original language, otherwise download any available)
    cmd = [
        "yt-dlp",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "origin,.*",
        "--skip-download",
        "-o", temp_sub_prefix,
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(f"yt-dlp sub download stdout: {result.stdout[:500]}")
    
    # Find downloaded subtitle file with priority
    sub_files = glob.glob(temp_sub_prefix + "*")
    vtt_file = None
    
    # Priority 1: Vietnamese (.vi.vtt)
    vtt_file = next((f for f in sub_files if f.endswith(".vi.vtt")), None)
    
    # Priority 2: Other languages (non-English)
    if not vtt_file:
        for f in sub_files:
            if f.endswith(".vtt") and not f.endswith(".en.vtt"):
                vtt_file = f
                break
                
    # Priority 3: English or any remaining VTT
    if not vtt_file:
        for f in sub_files:
            if f.endswith(".vtt"):
                vtt_file = f
                break
            
    if not vtt_file or not os.path.exists(vtt_file):
        logger.warning(f"No subtitle file downloaded. yt-dlp stderr: {result.stderr[:500]}")
        raise ValueError("Video này không có phụ đề có sẵn.")

    logger.info(f"Found downloaded subtitle: {vtt_file}")
    is_vietnamese = vtt_file.endswith(".vi.vtt")
    
    # Parse WebVTT file
    segments = []
    with open(vtt_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex to find timestamp blocks: 00:00:01.000 --> 00:00:04.000
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*\n(.*?)(?=\n\s*\n|\n\d|\Z)", 
        re.DOTALL
    )

    matches = pattern.findall(content)
    logger.info(f"Parsed {len(matches)} subtitle matches raw.")

    seg_idx = 0
    for start_str, end_str, text_block in matches:
        start_time = parse_vtt_time(start_str)
        end_time = parse_vtt_time(end_str)
        
        # Clean text: remove HTML tags, formatting cues, and extra whitespace
        text = re.sub(r"<[^>]*>", "", text_block)
        text = "\n".join([line.strip() for line in text.split("\n") if line.strip()])
        # Remove duplicates/redundancies often found in auto-captions
        lines = text.split("\n")
        unique_lines = []
        for line in lines:
            if not unique_lines or unique_lines[-1] != line:
                unique_lines.append(line)
        text = " ".join(unique_lines).strip()
        
        if not text:
            continue
            
        seg_data = {
            "start": start_time,
            "end": end_time,
            "text": text,
            "speaker": "Speaker 1"
        }
        if is_vietnamese:
            seg_data["translation"] = text  # Directly assign translation if already Vietnamese
            
        segments.append(seg_data)
        seg_idx += 1

    # Cleanup temp sub files
    for f in sub_files:
        try:
            os.remove(f)
        except Exception:
            pass

    logger.info(f"Successfully loaded {len(segments)} segments from YouTube subtitles.")
    return segments


def _frames_differ(prev_gray, curr_gray, threshold=15.0):
    """Compare two grayscale subtitle crops using Mean Absolute Difference.
    Returns True if the subtitle text has likely changed between frames."""
    import cv2
    import numpy as np
    if prev_gray is None:
        return True
    if prev_gray.shape != curr_gray.shape:
        return True
    diff = cv2.absdiff(prev_gray, curr_gray)
    mean_diff = np.mean(diff)
    return mean_diff > threshold


def _find_subtitle_bounding_box(gray_img):
    """
    Find subtitle bounding box using contour detection on CPU.
    Returns (x, y, w, h) or None if no subtitle-like shape is found.
    """
    import cv2
    # Threshold to isolate bright text (subtitles are usually white/yellow/bright gray)
    _, thresh = cv2.threshold(gray_img, 200, 255, cv2.THRESH_BINARY)
    
    # Morphological opening to merge characters into words/sentences
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    dilated = cv2.dilate(thresh, kernel, iterations=1)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bbox_list = []
    h_img, w_img = gray_img.shape[:2]
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        
        # Subtitle contour characteristics:
        # 1. Height should be reasonable (e.g. 8px to 100px)
        # 2. Width should not be tiny (e.g. > 15px)
        # 3. Position should be centered horizontally to some degree
        if 8 < h < 100 and w > 15:
            center_x = x + w / 2
            if w_img * 0.15 < center_x < w_img * 0.85:
                bbox_list.append((x, y, w, h))
                
    if not bbox_list:
        return None
        
    # Merge all bounding boxes
    x_min = min(b[0] for b in bbox_list)
    y_min = min(b[1] for b in bbox_list)
    x_max = max(b[0] + b[2] for b in bbox_list)
    y_max = max(b[1] + b[3] for b in bbox_list)
    
    # Add 10% padding
    pad_x = int((x_max - x_min) * 0.10)
    pad_y = int((y_max - y_min) * 0.10)
    
    # Clip to image boundaries
    x_start = max(0, x_min - pad_x)
    y_start = max(0, y_min - pad_y)
    x_end = min(w_img, x_max + pad_x)
    y_end = min(h_img, y_max + pad_y)
    
    return x_start, y_start, x_end - x_start, y_end - y_start


def _preprocess_for_ocr(gray_crop):
    """Enhance image for better OCR accuracy.
    Pipeline: CLAHE contrast -> Sharpen edges -> Upscale 2x."""
    import cv2
    import numpy as np

    # 1. CLAHE - Adaptive local contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray_crop)

    # 2. Sharpen - Enhance text edges
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)

    # 3. Upscale 2x - Better recognition for small text
    h, w = sharpened.shape[:2]
    upscaled = cv2.resize(sharpened, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    return upscaled


def _refine_with_gemini_vision(segments: list, keyframes: dict, api_key: str):
    """Layer 2: Use Gemini Vision API to refine OCR text and translate in one step.
    keyframes: dict mapping segment index -> base64-encoded JPEG image of the subtitle region.
    Only processes segments that don't already have a translation."""
    import requests
    import json
    import base64

    # Filter segments needing refinement (no translation yet)
    pending = [(i, seg) for i, seg in enumerate(segments) if not seg.get("translation")]
    if not pending:
        logger.info("Gemini Vision: Tất cả segments đã có bản dịch, bỏ qua tinh chỉnh.")
        return segments

    BATCH_SIZE = 10
    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
    logger.info(f"Gemini Vision: Tinh chỉnh {len(pending)} segments trong {len(batches)} batch...")

    for batch_idx, batch in enumerate(batches):
        try:
            parts = []
            # Build multi-part prompt with images
            instruction = (
                "Bạn là chuyên gia OCR và dịch thuật phụ đề video. "
                "Dưới đây là các ảnh chụp vùng phụ đề trên video. "
                "Với mỗi ảnh, hãy: (1) Đọc chính xác chữ trên ảnh, (2) Dịch sang tiếng Việt tự nhiên cho lồng tiếng.\n"
                "Lưu ý đặc biệt về tên nhân vật hoạt hình: "
                "Nobita/大雄 -> 'Nô Bi Ta', Shizuka/静香 -> 'Xu Ka', Suneo/小夫 -> 'Xê Kô', "
                "Jaian/胖虎 -> 'Chai En', Doraemon/哆啦A梦 -> 'Đô Rê Mon', Conan/柯南 -> 'Cô Nan'.\n\n"
                f"Trả về CHÍNH XÁC một mảng JSON gồm {len(batch)} phần tử, mỗi phần tử là object có 2 trường:\n"
                '- "text": chữ gốc đọc được trên ảnh (đã sửa lỗi OCR)\n'
                '- "translation": bản dịch tiếng Việt\n'
                'Ví dụ: [{"text": "大雄来了", "translation": "Nô Bi Ta đến rồi"}]\n'
                "Không markdown, chỉ JSON thuần."
            )
            parts.append({"text": instruction})

            for idx_in_batch, (seg_idx, seg) in enumerate(batch):
                ocr_text = seg.get("text", "")
                parts.append({"text": f"\n--- Ảnh {idx_in_batch + 1} (OCR thô: \"{ocr_text}\") ---"})
                if seg_idx in keyframes:
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": keyframes[seg_idx]
                        }
                    })
                else:
                    parts.append({"text": f"[Không có ảnh, chỉ dựa vào OCR thô: \"{ocr_text}\"]"})

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            payload = {"contents": [{"parts": parts}]}
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60.0)
            res.raise_for_status()
            res_data = res.json()
            res_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Parse JSON array from response
            json_match = re.search(r'\[.*\]', res_text, re.DOTALL)
            if json_match:
                refined_list = json.loads(json_match.group(0))
                if len(refined_list) == len(batch):
                    for idx_in_batch, (seg_idx, seg) in enumerate(batch):
                        item = refined_list[idx_in_batch]
                        if isinstance(item, dict):
                            if item.get("text"):
                                seg["text"] = item["text"]
                            if item.get("translation"):
                                seg["translation"] = item["translation"]
                        elif isinstance(item, str):
                            seg["translation"] = item
                    logger.info(f"Gemini Vision batch {batch_idx + 1}/{len(batches)}: Tinh chỉnh thành công {len(batch)} segments.")
                    continue
            logger.warning(f"Gemini Vision batch {batch_idx + 1}: Không parse được JSON, giữ nguyên kết quả EasyOCR.")
        except Exception as e:
            logger.warning(f"Gemini Vision batch {batch_idx + 1} lỗi: {e}. Giữ nguyên kết quả EasyOCR.")

    return segments


def ocr_video_subtitles(video_path: str) -> list:
    """
    Scan video frames using OpenCV and EasyOCR to extract hardcoded subtitles.
    Optimized with:
    - Smart Frame Detection: skip frames where subtitle region hasn't changed
    - Image Preprocessing: CLAHE + Sharpen + Upscale 2x for better accuracy
    - Gemini Vision refinement: optional 2nd layer to correct OCR errors and translate
    """
    import cv2
    import easyocr
    import numpy as np
    import base64
    from difflib import SequenceMatcher

    logger.info(f"Starting Video OCR (Smart Mode) on: {video_path}")
    reader = easyocr.Reader(['vi', 'ch_sim', 'ja', 'en'], gpu=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Không thể mở file video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = total_frames / fps if fps > 0 else 0

    # OCR settings - subtitle region is bottom 50% (from middle of the screen downward)
    crop_y_start = int(height * 0.50)

    # Sample every 1.0 second instead of 0.5s for speed
    sample_interval = max(1, int(fps))
    logger.info(f"Video: {duration_sec:.0f}s, FPS: {fps:.0f}, Total frames: {total_frames}, Sample interval: {sample_interval} frames")

    raw_frames = []
    keyframe_images = {}   # raw_frame_index -> base64 JPEG for Gemini Vision
    frame_idx = 0
    prev_gray_crop = None
    frames_skipped = 0
    frames_ocred = 0

    # Streaming batch buffers
    BATCH_SIZE = 16
    batch_images: list = []        # preprocessed grayscale crops
    batch_meta: list = []          # (timestamp, original_color_crop)

    def _flush_batch():
        """Run OCR on accumulated batch and append results to raw_frames."""
        nonlocal frames_ocred
        if not batch_images:
            return
        try:
            batch_results = reader.readtext_batched(
                batch_images,
                detail=0,
                paragraph=False,
                text_threshold=0.6,
                low_text=0.3,
                mag_ratio=1.5
            )
        except Exception as e:
            logger.warning(f"readtext_batched error: {e}. Falling back to sequential.")
            batch_results = [reader.readtext(img, detail=0) for img in batch_images]

        for i, results in enumerate(batch_results):
            timestamp, color_crop = batch_meta[i]
            text = " ".join(results).strip()
            # Clean text (keep Unicode characters)
            text = re.sub(r"[^\w\s.,!?'\"\-\(\)]", "", text)
            text = " ".join(text.split()).strip()

            frames_ocred += 1

            # Save keyframe for Gemini Vision refinement
            if text:
                try:
                    _, buffer = cv2.imencode('.jpg', color_crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    keyframe_images[len(raw_frames)] = base64.b64encode(buffer).decode('utf-8')
                except Exception:
                    pass

            raw_frames.append({
                "time": timestamp,
                "time_end": timestamp + 1.0,
                "text": text
            })

        batch_images.clear()
        batch_meta.clear()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            timestamp = frame_idx / fps

            # Crop the subtitle region (bottom 50%)
            half_crop = frame[crop_y_start:height, 0:width]
            gray = cv2.cvtColor(half_crop, cv2.COLOR_BGR2GRAY)

            # Smart Frame Detection: skip if subtitle region hasn't changed
            if not _frames_differ(prev_gray_crop, gray):
                frames_skipped += 1
                if raw_frames and raw_frames[-1]["text"]:
                    raw_frames[-1]["time_end"] = timestamp + 1.0
                # Also extend last item in batch_meta if batch not flushed yet
                # (no-op needed; flush handles its own timestamps)
                frame_idx += 1
                prev_gray_crop = gray
                continue

            prev_gray_crop = gray

            # --- Dynamic Cropping via contour detection ---
            bbox = _find_subtitle_bounding_box(gray)
            if bbox is not None:
                bx, by, bw, bh = bbox
                tight_gray = gray[by:by + bh, bx:bx + bw]
                tight_color = half_crop[by:by + bh, bx:bx + bw]
            else:
                tight_gray = gray
                tight_color = half_crop

            # Image Preprocessing Pipeline
            preprocessed = _preprocess_for_ocr(tight_gray)

            batch_images.append(preprocessed)
            batch_meta.append((timestamp, tight_color))

            # Flush when batch is full
            if len(batch_images) >= BATCH_SIZE:
                _flush_batch()

        frame_idx += 1

    # Flush any remaining frames in the last partial batch
    _flush_batch()

    cap.release()
    total_sampled = frames_skipped + frames_ocred
    skip_pct = (frames_skipped / total_sampled * 100) if total_sampled > 0 else 0
    logger.info(f"Smart OCR (Batched): {frames_ocred} frames quét, {frames_skipped} frames bỏ qua ({skip_pct:.0f}% tiết kiệm). Tổng: {len(raw_frames)} kết quả.")

    # Group continuous identical text into segments
    segments = []
    current_seg = None

    def similarity(s1, s2):
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

    for item in raw_frames:
        time_start = item["time"]
        time_end = item.get("time_end", time_start + 1.0)
        text = item["text"]

        if not text:
            if current_seg:
                if current_seg["end"] - current_seg["start"] >= 0.5:
                    segments.append(current_seg)
                current_seg = None
            continue

        if current_seg is None:
            current_seg = {
                "start": time_start,
                "end": time_end,
                "text": text,
                "speaker": "Speaker 1"
            }
        else:
            if similarity(current_seg["text"], text) > 0.65:
                current_seg["end"] = time_end
                if len(text) > len(current_seg["text"]):
                    current_seg["text"] = text
            else:
                if current_seg["end"] - current_seg["start"] >= 0.5:
                    segments.append(current_seg)
                current_seg = {
                    "start": time_start,
                    "end": time_end,
                    "text": text,
                    "speaker": "Speaker 1"
                }

    if current_seg and (current_seg["end"] - current_seg["start"] >= 0.5):
        segments.append(current_seg)

    # Final post-processing: remove noise
    cleaned_segments = []
    for s in segments:
        text = s["text"].strip()
        if len(text) <= 2 and not text.isalnum():
            continue
        cleaned_segments.append(s)

    # Auto-detect Vietnamese and assign translation to bypass translation step
    vietnamese_accents = re.compile(r'[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệđìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆĐÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ]')
    for s in cleaned_segments:
        s_text = s.get("text", "")
        if vietnamese_accents.search(s_text):
            s["translation"] = s_text

    # Layer 2: Gemini Vision refinement (if API key available)
    from app.config import settings
    api_key = settings.GEMINI_API_KEY.strip() if hasattr(settings, 'GEMINI_API_KEY') else ""
    if api_key and keyframe_images:
        # Map raw_frame indices to segment indices for keyframe lookup
        seg_keyframes = {}
        for seg_idx, seg in enumerate(cleaned_segments):
            # Find the closest raw_frame keyframe for this segment
            for raw_idx, b64_img in keyframe_images.items():
                if raw_idx < len(raw_frames):
                    raw_time = raw_frames[raw_idx]["time"]
                    if seg["start"] <= raw_time <= seg["end"]:
                        seg_keyframes[seg_idx] = b64_img
                        break
        if seg_keyframes:
            logger.info(f"Gemini Vision: Tinh chỉnh {len(seg_keyframes)} segments có keyframe...")
            _refine_with_gemini_vision(cleaned_segments, seg_keyframes, api_key)

    logger.info(f"OCR generated {len(cleaned_segments)} processed subtitle segments.")
    return cleaned_segments


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

def _prescan_video_context(segments: list, api_key: str) -> dict:
    """Pre-scan: Analyze transcript to auto-detect video type, character names,
    and Vietnamese phonetic mappings before translation begins.
    Returns a dict with video_type, characters, and tone info."""
    import requests
    import json

    # Sample up to 50 segments for analysis (enough to identify characters)
    sample_texts = []
    for seg in segments[:50]:
        text = seg.get("text", "").strip()
        if text:
            sample_texts.append(text)

    if not sample_texts:
        return {"video_type": "unknown", "characters": [], "tone": "neutral"}

    sample_transcript = "\n".join(sample_texts)

    prompt = (
        "You are an expert video content analyst. Analyze this transcript and return a JSON object.\n\n"
        "TRANSCRIPT:\n"
        f"{sample_transcript}\n\n"
        "Return ONLY a JSON object (no markdown) with this structure:\n"
        "{\n"
        '  "video_type": "anime/cartoon/movie/drama/education/tech/music/other",\n'
        '  "title_guess": "name of the show/movie if you can identify it, otherwise empty string",\n'
        '  "source_language": "zh/ja/en/ko/fr/etc",\n'
        '  "characters": [\n'
        '    {"original": "大雄", "aliases": ["Nobita", "のび太"], "vietnamese": "Nô Bi Ta"},\n'
        '    {"original": "静香", "aliases": ["Shizuka", "しずか"], "vietnamese": "Xu Ka"}\n'
        "  ],\n"
        '  "tone": "casual/formal/excited/childish/serious"\n'
        "}\n\n"
        "IMPORTANT RULES:\n"
        "1. For anime/cartoon/movie characters with well-known Vietnamese names, use the standard Vietnamese phonetic.\n"
        "2. Use SPACES between syllables so TTS reads smoothly (e.g., 'Nô Bi Ta' not 'Nôbita').\n"
        "3. Include ALL character name variants you find (Chinese, Japanese, English, common typos/OCR errors).\n"
        "4. If you recognize the show, list ALL main characters even if some don't appear in this sample.\n"
        "5. For real people or brands, keep original names unchanged.\n"
        "6. Return empty characters array if no fictional characters are found.\n"
    )

    import time as _time
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(1, 4):
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30.0)
            res.raise_for_status()
            res_data = res.json()
            res_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Parse JSON from response
            json_match = re.search(r'\{.*\}', res_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                chars = result.get("characters", [])
                logger.info(
                    f"Pre-scan: video_type={result.get('video_type', '?')}, "
                    f"title={result.get('title_guess', '?')}, "
                    f"characters={len(chars)}, tone={result.get('tone', '?')}"
                )
                return result
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "Too Many Requests" in err_str) and attempt < 3:
                wait = 30 * attempt
                logger.warning(f"Pre-scan 429 rate limit (lần {attempt}/3) - chờ {wait}s rồi thử lại...")
                _time.sleep(wait)
                continue
            logger.warning(f"Pre-scan thất bại: {e}. Sẽ dịch không có context nhân vật.")
            break

    return {"video_type": "unknown", "characters": [], "tone": "neutral"}


def _build_character_map_prompt(prescan: dict) -> str:
    """Build a character name reference block from pre-scan results
    to inject into translation prompt."""
    characters = prescan.get("characters", [])
    if not characters:
        return ""

    lines = ["\nCHARACTER NAME REFERENCE (You MUST follow these exact Vietnamese names):"]
    for char in characters:
        original = char.get("original", "")
        vietnamese = char.get("vietnamese", "")
        aliases = char.get("aliases", [])
        if original and vietnamese:
            alias_str = " / ".join([original] + aliases) if aliases else original
            lines.append(f"  - {alias_str} → '{vietnamese}'")

    lines.append("")
    return "\n".join(lines)


def _call_gemini_api_http(prompt: str, api_key: str) -> str:
    """Gọi trực tiếp API REST của Gemini 2.5 Flash bằng thư viện requests"""
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    response = requests.post(url, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()
    res_data = response.json()
    return res_data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq_api_http(prompt: str, api_key: str) -> str:
    """Gọi trực tiếp API tương thích OpenAI của Groq bằng thư viện requests"""
    import requests
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()
    res_data = response.json()
    return res_data["choices"][0]["message"]["content"].strip()


def _call_openrouter_api_http(prompt: str, api_key: str) -> str:
    """Gọi trực tiếp API của OpenRouter bằng thư viện requests"""
    import requests
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nguyeenhoangloi-spec/Voice",
        "X-Title": "Voice AI Platform"
    }
    payload = {
        "model": "meta-llama/llama-3-8b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()
    res_data = response.json()
    return res_data["choices"][0]["message"]["content"].strip()


def _call_github_api_http(prompt: str, api_key: str) -> str:
    """Gọi trực tiếp API GitHub Models bằng thư viện requests"""
    import requests
    url = "https://models.inference.ai.azure.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()
    res_data = response.json()
    return res_data["choices"][0]["message"]["content"].strip()


def _call_cohere_api_http(prompt: str, api_key: str) -> str:
    """Gọi trực tiếp API của Cohere bằng thư viện requests"""
    import requests
    url = "https://api.cohere.com/v1/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "command-r-plus",
        "message": prompt,
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=payload, timeout=45.0)
    response.raise_for_status()
    res_data = response.json()
    return res_data["text"].strip()


def _translate_batch_with_llm(prompt: str, expected_count: int) -> list:
    """Thử dịch thuật một batch bằng các LLM API khả dụng theo thứ tự ưu tiên."""
    from app.config import settings
    import time as _time
    import json
    import re

    # Tạo danh sách các provider khả dụng theo thứ tự ưu tiên
    providers = []
    if settings.GEMINI_API_KEY.strip():
        providers.append(("gemini", settings.GEMINI_API_KEY.strip()))
    if settings.GROQ_API_KEY.strip():
        providers.append(("groq", settings.GROQ_API_KEY.strip()))
    if settings.OPENROUTER_API_KEY.strip():
        providers.append(("openrouter", settings.OPENROUTER_API_KEY.strip()))
    if settings.GITHUB_API_KEY.strip():
        providers.append(("github", settings.GITHUB_API_KEY.strip()))
    if settings.COHERE_API_KEY.strip():
        providers.append(("cohere", settings.COHERE_API_KEY.strip()))

    if not providers:
        logger.warning("Không có API Key nào được cấu hình trong settings. Bỏ qua dịch LLM.")
        return []

    for provider_name, api_key in providers:
        logger.info(f"Đang thử dịch batch bằng API: {provider_name.upper()}...")
        for attempt in range(1, 4):
            try:
                res_text = ""
                if provider_name == "gemini":
                    if api_key.startswith("AQ."):
                        res_text = _call_gemini_api_http(prompt, api_key)
                    else:
                        from google import genai
                        client = genai.Client(api_key=api_key)
                        response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                        )
                        res_text = response.text.strip()
                elif provider_name == "groq":
                    res_text = _call_groq_api_http(prompt, api_key)
                elif provider_name == "openrouter":
                    res_text = _call_openrouter_api_http(prompt, api_key)
                elif provider_name == "github":
                    res_text = _call_github_api_http(prompt, api_key)
                elif provider_name == "cohere":
                    res_text = _call_cohere_api_http(prompt, api_key)

                # Trích xuất mảng JSON từ phản hồi của LLM
                json_match = re.search(r'\[\s*".*"\s*\]', res_text, re.DOTALL) or re.search(r'\[.*\]', res_text, re.DOTALL)
                if json_match:
                    translated_list = json.loads(json_match.group(0))
                    if len(translated_list) == expected_count:
                        logger.info(f"Dịch thành công {expected_count} câu bằng {provider_name.upper()} API.")
                        return translated_list
                    else:
                        logger.warning(
                            f"Kết quả {provider_name.upper()} trả về số câu không khớp: "
                            f"nhận {len(translated_list)} vs mong đợi {expected_count}."
                        )
                else:
                    logger.warning(f"Không thể parse JSON từ kết quả của {provider_name.upper()}.")

            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "Too Many Requests" in err_str
                is_retryable = (
                    is_rate_limit or "503" in err_str or
                    "UNAVAILABLE" in err_str or
                    "timeout" in err_str.lower() or "connection" in err_str.lower()
                )
                if is_retryable and attempt < 3:
                    wait_sec = 15 * attempt if is_rate_limit else 5 * attempt
                    logger.warning(f"Lỗi {provider_name.upper()} (lần {attempt}/3): {e} - thử lại sau {wait_sec}s...")
                    _time.sleep(wait_sec)
                    continue
                logger.warning(f"Lỗi {provider_name.upper()} API (lần {attempt}/3): {e}.")
                break  # Thất bại với provider này, chuyển sang provider tiếp theo trong danh sách

    logger.warning("Đã thử tất cả các nhà cung cấp dịch thuật LLM cấu hình sẵn nhưng đều thất bại.")
    return []


def translate_segments(segments: list, target_lang: str = "vi", video_context: str = "neutral", video_topic: str = "") -> list:
    """Translate each segment text to target language using LLM API (if available) or Google Translate"""
    import sys
    if "pytest" not in sys.modules:
        import os
        from pathlib import Path
        from dotenv import load_dotenv
        # Ép buộc load lại file .env mới nhất trên đĩa cứng vào os.environ để tránh cache biến môi trường
        base_dir = Path(__file__).resolve().parent.parent.parent
        load_dotenv(base_dir / ".env", override=True)

        from app.config import settings
        # Cập nhật lại giá trị các API KEY trong settings đối tượng
        settings.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
        settings.GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
        settings.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
        settings.GITHUB_API_KEY = os.getenv("GITHUB_API_KEY", "").strip()
        settings.COHERE_API_KEY = os.getenv("COHERE_API_KEY", "").strip()

    from app.config import settings

    # Nếu tất cả các segment đều đã có sẵn bản dịch tiếng Việt, bypass dịch thuật để tiết kiệm API và tăng độ chính xác
    if all(seg.get("translation") for seg in segments):
        logger.info("Tất cả segments đều đã có sẵn bản dịch (phụ đề tiếng Việt). Bỏ qua bước dịch thuật.")
        return segments

    # Sử dụng LLM API nếu có bất kỳ API Key nào khả dụng
    has_llm_key = (
        settings.GEMINI_API_KEY.strip() or
        settings.GROQ_API_KEY.strip() or
        settings.OPENROUTER_API_KEY.strip() or
        settings.GITHUB_API_KEY.strip() or
        settings.COHERE_API_KEY.strip()
    )
    if has_llm_key:
        import time as _time
        logger.info("Sử dụng LLM API dịch thuật...")

        # === PRE-SCAN: Tự động nhận dạng video và trích xuất nhân vật ===
        detected_tone = "neutral"
        detected_type = "unknown"
        detected_title = ""
        character_map_block = ""

        gemini_key = settings.GEMINI_API_KEY.strip()
        if gemini_key:
            logger.info("Chạy pre-scan ngữ cảnh video bằng Gemini...")
            prescan = _prescan_video_context(segments, gemini_key)
            character_map_block = _build_character_map_prompt(prescan)
            detected_tone = prescan.get("tone", "neutral")
            detected_type = prescan.get("video_type", "unknown")
            detected_title = prescan.get("title_guess", "")
            # Rate limit: chờ 3s sau pre-scan để tránh 429 Too Many Requests
            _time.sleep(3)

        # Chia nhỏ segments thành các batch để tránh timeout do prompt quá dài
        BATCH_SIZE = 15
        all_translated = True
        batches = [segments[i:i + BATCH_SIZE] for i in range(0, len(segments), BATCH_SIZE)]
        logger.info(f"Chia {len(segments)} segments thành {len(batches)} batch (mỗi batch tối đa {BATCH_SIZE} câu).")

        # Cross-batch context: lưu câu dịch cuối mỗi batch để truyền sang batch sau
        previous_translations = []

        for batch_idx, batch in enumerate(batches):
            batch_start_global = batch_idx * BATCH_SIZE
            logger.info(f"Đang dịch batch {batch_idx + 1}/{len(batches)} ({len(batch)} câu, segment {batch_start_global}-{batch_start_global + len(batch) - 1})...")

            batch_success = False

            # === PROMPT CẢI TIẾN: Tiếng Việt + Hard Limit + Dynamic Character Map ===
            prompt = (
                "Bạn là chuyên gia lồng tiếng phim ảnh hàng đầu Việt Nam với 20 năm kinh nghiệm.\n"
                f"Thể loại: {detected_type} | Tên phim: {detected_title or video_topic} | Giọng điệu: {detected_tone}\n\n"
                "NHIỆM VỤ: Dịch các câu dưới đây sang tiếng Việt dùng để lồng tiếng (dubbing).\n\n"
                "QUY TẮC ƯU TIÊN (Theo thứ tự quan trọng):\n"
                "1. BẢO TOÀN NỘI DUNG (QUAN TRỌNG NHẤT): Phải dịch chính xác 100% ý của câu gốc. "
                "TUYỆT ĐỐI KHÔNG thêm thắt thông tin, KHÔNG tự bịa chuyện, KHÔNG lược bỏ ý chính.\n\n"
                "2. VĂN NÓI TỰ NHIÊN: Dùng cấu trúc câu nói đời thường, ngắt nghỉ đúng chỗ. "
                "TUYỆT ĐỐI KHÔNG dịch word-by-word cứng nhắc. Phải thể hiện được cảm xúc "
                f"(giọng điệu: {detected_tone}).\n\n"
                "3. TÊN NHÂN VẬT: Nếu có phần CHARACTER NAME REFERENCE bên dưới, BẮT BUỘC dùng đúng tên "
                "tiếng Việt đó. Tên thật người/thương hiệu thì giữ nguyên.\n\n"
                "4. THUẬT NGỮ KỸ THUẬT: Giữ nguyên tiếng Anh nếu tiếng Việt không có từ thay thế tự nhiên.\n\n"
                "5. ĐỘ DÀI & PHONG CÁCH (Gợi ý mềm - KHÔNG phải giới hạn cứng): \n"
                "   - Mục tiêu: dịch ngắn gọn, đủ ý, đúng chất SUBTITLE (không dư thừa, không filler words). \n"
                "   - Số từ gợi ý (~N từ) chỉ là tham khảo về nhịp thời gian. \n"
                "   - NẾU câu gốc có nhiều ý quan trọng → ĐƯỢC PHÉP vượt quá ~N từ để dịch đầy đủ. \n"
                "   - TUYỆT ĐỐI KHÔNG cắt bỏ ý chính để ép vừa giới hạn số từ. \n"
                "   - Hệ thống sẽ TỰ ĐỘNG điều chỉnh tốc độ đọc để khớp thời lượng video.\n\n"
                "6. ĐỊNH DẠNG: CHỈ TRẢ VỀ một mảng JSON chuỗi, đúng thứ tự. KHÔNG dùng markdown, KHÔNG giải thích gì thêm.\n"
                "   Ví dụ: [\"câu một\", \"câu hai\"]\n"
            )

            # Inject dynamic character map from pre-scan
            if character_map_block:
                prompt += character_map_block

            # Cross-batch context: inject previous translations for continuity
            if previous_translations:
                prompt += "\n[PREVIOUS BATCH TRANSLATIONS for context continuity — maintain consistent style and names]:\n"
                for pt in previous_translations[-5:]:
                    prompt += f"  \"{pt['original']}\" → \"{pt['translation']}\"\n"
                prompt += "\n"

            prompt += f"\nSegments (batch {batch_idx + 1}/{len(batches)}):\n"

            for local_idx, seg in enumerate(batch):
                global_idx = batch_start_global + local_idx
                duration = seg.get("end", 0.0) - seg.get("start", 0.0)
                orig_text = seg.get("text", "").strip()
                orig_words = len(orig_text.split()) if orig_text else 0

                # Target word count (soft guide)
                max_words = max(1, int(orig_words * 1.20))
                max_words = max(max_words, max(1, int(duration * 2.6)))
                max_words = min(max_words, max(1, int(duration * 3.2)))

                # Include previous segment as context clue
                if local_idx > 0:
                    prev_text = batch[local_idx - 1].get("text", "").strip()
                elif global_idx > 0:
                    prev_text = segments[global_idx - 1].get("text", "").strip()
                else:
                    prev_text = ""

                if prev_text:
                    prompt += f"[{local_idx}] (~{max_words} words, {duration:.1f}s)\n  [PREV]: {prev_text}\n  [CURR]: {orig_text}\n\n"
                else:
                    prompt += f"[{local_idx}] (~{max_words} words, {duration:.1f}s)\n  [CURR]: {orig_text}\n\n"

            # Thực hiện dịch thuật batch bằng LLM có fallback
            translated_list = _translate_batch_with_llm(prompt, len(batch))
            if translated_list:
                for local_idx, trans in enumerate(translated_list):
                    batch[local_idx]["translation"] = trans
                # Lưu context cho batch tiếp theo
                for seg in batch:
                    previous_translations.append({
                        "original": seg.get("text", ""),
                        "translation": seg.get("translation", "")
                    })
                batch_success = True
                # Chờ nhẹ giữa các batch để tránh spam
                if batch_idx < len(batches) - 1:
                    _time.sleep(2)

            if not batch_success:
                all_translated = False
                # Fallback từng câu trong batch thất bại sang Google Translate
                from deep_translator import GoogleTranslator
                translator = GoogleTranslator(source="auto", target=target_lang)
                for seg in batch:
                    if not seg.get("translation"):
                        try:
                            seg["translation"] = translator.translate(seg["text"])
                        except Exception as e:
                            logger.warning(f"Google Translate fallback failed: {e}")
                            seg["translation"] = seg["text"]
                    # Vẫn lưu context cho batch tiếp theo dù fallback
                    previous_translations.append({
                        "original": seg.get("text", ""),
                        "translation": seg.get("translation", "")
                    })
                logger.info(f"Batch {batch_idx + 1}: Đã fallback {len(batch)} câu sang Google Translate.")

        if all_translated:
            logger.info(f"Đã dịch thành công toàn bộ {len(segments)} câu bằng LLM API.")
        else:
            logger.info(f"Hoàn tất dịch {len(segments)} câu (một số batch dùng LLM, một số fallback Google Translate).")
        return segments

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
    - Natural Vietnamese speech: ~2.8 words/sec at normal rate
    - Only speed up Edge TTS if words exceed natural threshold (max +20%)
    - If translation still too long after rate boost, compress at sentence boundaries
    - NOTE: The merge step will do a final atempo stretch (max 1.4x) + truncate-to-fit
    """
    translation = seg.get("translation", seg.get("text", ""))
    start_time = seg.get("start", 0.0)
    end_time = seg.get("end", start_time + 3.0)
    duration = max(end_time - start_time, 0.5)  # at least 0.5s

    words = translation.split()
    word_count = len(words)

    # TỐC ĐỘ TỰ NHIÊN: 2.8 từ/giây (Không đổi)
    NATURAL_WPS = 2.8
    # Tăng ngưỡng tối đa: trước khi cắt chữ, hệ thống sẽ tăng tốc TTS + atempo (max 1.5x)
    MAX_ALLOWED_WPS = 4.5

    # Adjust base rate from video context
    rate_map = {"fast": 5, "neutral": 0, "slow": -5, "teaching": -8}
    base_rate_pct = rate_map.get(video_context.lower(), 0)

    wps = word_count / duration if duration > 0 else NATURAL_WPS
    extra_speed_pct = 0

    # Tự động tăng tốc độ TTS nếu câu dài hơn tốc độ tự nhiên.
    # Giới hạn tối đa +60% để Edge TTS vẫn còn nghe được.
    # Phần còn lại sẽ được bù bằng ffmpeg atempo trong bước overlay.
    if wps > NATURAL_WPS:
        extra_speed_pct = int((wps - NATURAL_WPS) * 15)
        extra_speed_pct = min(extra_speed_pct, 60)

    final_rate_pct = base_rate_pct + extra_speed_pct

    # Format rate for Edge TTS (e.g. "+15%", "-5%", "+0%")
    rate_str = f"+{final_rate_pct}%" if final_rate_pct >= 0 else f"{final_rate_pct}%"

    # Chỉ cảnh báo log — KHÔNG cắt chữ ở đây nữa.
    # Việc khớp thời lượng sẽ do bước atempo trong overlay xử lý.
    if word_count > int(duration * MAX_ALLOWED_WPS):
        logger.warning(
            f"Câu rất dài ({word_count} từ / {duration:.1f}s, {wps:.1f} wps). "
            f"Sẽ dùng atempo tối đa 1.5x để khớp khung hình."
        )

    logger.info(f"Segment: {word_count} từ trong {duration:.1f}s (wps: {wps:.2f}) → TTS Rate: {rate_str}")

    return {
        "text": translation.strip(),
        "rate": rate_str
    }


def generate_tts_audio(text: str, output_path: str, voice: str = "vi-VN-HoaiMyNeural",
                        rate: str = "+0%") -> str:
    """
    Generate TTS audio using Microsoft Edge TTS (free) or Kokoro TTS (local, 50 voices) with retry logic.
    """
    import asyncio
    import concurrent.futures
    import time
    import random

    clean_text = text.strip()
    clean_text = clean_text.rstrip('…').rstrip('.')
    if clean_text and clean_text[-1] not in '.!?,;:':
        clean_text += '.'

    # ── Check if we should use Kokoro TTS ──
    # Kokoro voice IDs start with gender/lang prefixes (e.g. af_bella, am_adam, bf_emma, etc.)
    if voice.startswith(("af_", "am_", "bf_", "bm_", "ef_", "em_", "ff_", "hf_", "hm_", "if_", "im_", "pf_", "pm_", "jf_", "jm_", "zf_")):
        from app.services.kokoro_service import KokoroService
        speed = 1.0
        try:
            if rate.startswith("+"):
                speed = 1.0 + float(rate.replace("+", "").replace("%", "")) / 100.0
            elif rate.startswith("-"):
                speed = 1.0 - float(rate.replace("-", "").replace("%", "")) / 100.0
        except ValueError:
            speed = 1.0

        # Determine target language code from voice prefix
        lang_code = "en"
        voice_prefix = voice[:2]
        if voice_prefix in ("af", "am", "bf", "bm"):
            lang_code = "en"
        elif voice_prefix in ("ef", "em"):
            lang_code = "es"
        elif voice_prefix == "ff":
            lang_code = "fr"
        elif voice_prefix in ("hf", "hm"):
            lang_code = "hi"
        elif voice_prefix in ("if", "im"):
            lang_code = "it"
        elif voice_prefix in ("pf", "pm"):
            lang_code = "pt"
        elif voice_prefix in ("jf", "jm"):
            lang_code = "ja"
        elif voice_prefix == "zf":
            lang_code = "zh"

        service = KokoroService()
        
        # Remove old file to ensure fresh generation
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        success = service.generate_speech(
            text=clean_text,
            voice_id=voice,
            lang=lang_code,
            output_path=output_path,
            speed=speed
        )
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return output_path
        
        logger.warning(f"Kokoro TTS failed for voice {voice}, text: '{clean_text[:20]}...'. Falling back to Edge-TTS.")
        # Fallback to default edge-tts voice if kokoro fails
        voice = "vi-VN-HoaiMyNeural"

    # ── Check if we should use VieNeu TTS ──
    if voice.startswith("vieneu_"):
        from app.services.vieneu_service import VieneuService
        vieneu_voice_id = voice.replace("vieneu_", "")
        service = VieneuService()
        
        # Remove old file to ensure fresh generation
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        success = service.generate_speech(
            text=clean_text,
            voice_id=vieneu_voice_id,
            output_path=output_path
        )
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return output_path
            
        logger.warning(f"Vieneu TTS failed for voice {voice}, text: '{clean_text[:20]}...'. Falling back to Edge-TTS.")
        voice = "vi-VN-HoaiMyNeural"

    # ── Check if we should use TikTok/CapCut TTS ──
    # TikTok voice IDs start with "vi_vn_" or "en_us_" (e.g. vi_vn_002, vi_vn_001, en_us_001, en_us_006, en_us_ghostface)
    if voice.startswith(("vi_vn_", "en_us_ghostface")) or (voice.startswith("en_us_") and len(voice) > 6 and voice[6:].isdigit()):
        from app.services.tiktok_service import TiktokService
        tiktok_service = TiktokService()
        
        # Remove old file to ensure fresh generation
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

        # Gửi request sinh giọng qua TikTok public API
        success = tiktok_service.generate_speech(
            text=clean_text,
            voice_id=voice,
            output_path=output_path
        )
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return output_path
        
        logger.warning(f"TikTok TTS failed for voice {voice}, text: '{clean_text[:20]}...'. Falling back to Edge-TTS.")
        voice = "vi-VN-HoaiMyNeural"

    # Edge TTS logic
    import edge_tts

    async def _gen():
        communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
        await communicate.save(output_path)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Remove old file to ensure fresh generation
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

            try:
                asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(asyncio.run, _gen()).result()
            except RuntimeError:
                asyncio.run(_gen())

            # Verify file created and valid (> 100 bytes)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return output_path

            raise ValueError("Sinh file TTS rỗng hoặc không tồn tại.")
        except Exception as e:
            logger.warning(f"Lần thử {attempt}/{max_retries} sinh TTS thất bại cho text '{clean_text[:20]}...': {e}")
            if attempt < max_retries:
                jitter = random.uniform(0.5, 1.5)
                time.sleep(2.0 * attempt + jitter)
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


def _adjust_audio_speed(audio_path: str, speed_factor: float) -> str:
    """Tăng tốc độ âm thanh sử dụng bộ lọc FFmpeg atempo (giữ nguyên cao độ giọng).
    speed_factor giới hạn trong khoảng [0.5, 2.0]."""
    import subprocess
    
    if abs(speed_factor - 1.0) < 0.05:
        return audio_path  # Không cần điều chỉnh nếu lệch quá ít (< 5%)
        
    ffmpeg = get_ffmpeg_path()
    speed_factor = max(0.5, min(speed_factor, 2.0))
    
    temp_dir = os.path.dirname(audio_path)
    temp_out = os.path.join(temp_dir, "speedup_" + os.path.basename(audio_path))
    
    try:
        cmd = [
            ffmpeg, "-y",
            "-i", audio_path,
            "-filter:a", f"atempo={speed_factor:.2f}",
            "-vn",
            temp_out
        ]
        res = subprocess.run(cmd, capture_output=True, check=True)
        if os.path.exists(temp_out) and os.path.getsize(temp_out) > 100:
            os.replace(temp_out, audio_path)
            logger.info(f"Khớp nhịp tự động: tăng tốc {speed_factor:.2f}x cho vừa slot video.")
            return audio_path
    except Exception as e:
        logger.warning(f"Không thể co kéo tốc độ âm thanh bằng FFmpeg: {e}")
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass
    return audio_path


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

    # Tăng workers lên 10 để tăng tốc độ tải TTS song song đáng kể (rất an toàn, không lo bị Microsoft block)
    max_workers = 10
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

            # ─── KHỚP NHỊP TỰ ĐỘNG: Co dãn âm thanh bằng FFmpeg atempo nếu dài hơn slot video ─
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
                    # Nếu âm thanh thực tế dài hơn slot video
                    if actual_ms > slot_ms:
                        speed_factor = actual_ms / slot_ms
                        # Giới hạn tăng tốc tối đa 1.4x để tránh biến dạng giọng nói quá nhiều
                        speed_factor = min(speed_factor, 1.4)
                        
                        if speed_factor > 1.05:  # Lệch trên 5% mới co dãn
                            _adjust_audio_speed(output_path, speed_factor)
                            # Cập nhật lại thời lượng sau khi tăng tốc
                            try:
                                actual_ms = len(_AS.from_file(output_path))
                            except Exception:
                                pass
                                
                    if actual_ms > slot_ms * 1.2:
                        logger.info(f"Seg {idx}: audio={actual_ms:.0f}ms, slot={slot_ms:.0f}ms (vẫn đè nhẹ sau khi tăng tốc tối đa 1.4x)")
                except Exception as _e:
                    logger.warning(f"Seg {idx}: auto-stretch check FAILED ({type(_e).__name__}: {_e})")
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
                          bg_volume_db: int = -18,
                          burn_subtitles: bool = False,
                          srt_path: str = "") -> tuple:
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

     # Overlay each TTS segment at its correct timestamp (TRUNCATE-TO-FIT mode)
    # Mỗi câu thoại LUÔN bắt đầu đúng thời điểm gốc trên video.
    # Nếu câu trước dài quá → cắt + fade-out 200ms, KHÔNG đẩy lùi câu sau.
    overlay_count = 0

    for idx, seg in enumerate(segments):
        if not seg.get("audio_path") or not os.path.exists(seg["audio_path"]):
            continue
        try:
            tts_audio = AudioSegment.from_file(seg["audio_path"])
            start_ms = int(seg["start"] * 1000)

            # Tính thời lượng tối đa cho phép cho câu thoại này
            # = thời lượng slot gốc trên video (end - start)
            slot_end_ms = int(seg.get("end", seg["start"] + 3.0) * 1000)
            max_duration_ms = slot_end_ms - start_ms

            # Nếu audio dài hơn slot → ưu tiên nén bằng ffmpeg atempo (tối đa 1.5x)
            # trước khi cắt, để đảm bảo đọc hết câu mà không mất chữ cuối.
            MAX_ATEMPO = 1.5
            if max_duration_ms > 0 and len(tts_audio) > max_duration_ms:
                original_len = len(tts_audio)
                speed_factor = original_len / max_duration_ms  # e.g. 1.2 nếu dài hơn 20%

                if speed_factor <= MAX_ATEMPO:
                    # Trường hợp 1: Có thể nén vừa khít trong slot
                    audio_path = seg["audio_path"]
                    _adjust_audio_speed(audio_path, speed_factor)
                    try:
                        tts_audio = AudioSegment.from_file(audio_path)
                        logger.info(
                            f"Seg {idx}: atempo {speed_factor:.2f}x → {original_len}ms → "
                            f"{len(tts_audio)}ms (khớp slot {max_duration_ms}ms)"
                        )
                    except Exception as reload_err:
                        logger.warning(f"Seg {idx}: Không đọc lại audio sau atempo: {reload_err}")
                else:
                    # Trường hợp 2: Quá dài ngay cả ở 1.5x → nén tối đa rồi để tràn nhẹ
                    audio_path = seg["audio_path"]
                    _adjust_audio_speed(audio_path, MAX_ATEMPO)
                    try:
                        tts_audio = AudioSegment.from_file(audio_path)
                    except Exception:
                        pass
                    logger.warning(
                        f"Seg {idx}: audio {original_len}ms vẫn quá dài so với slot {max_duration_ms}ms "
                        f"ngay cả ở {MAX_ATEMPO}x. Cho phép tràn nhẹ để không mất chữ."
                    )

            # Nếu sau atempo vẫn còn dài hơn 120% slot → cắt cứng với fade-out 100ms (dự phòng)
            hard_cut_limit = int(max_duration_ms * 1.2) if max_duration_ms > 0 else len(tts_audio)
            if max_duration_ms > 0 and len(tts_audio) > hard_cut_limit:
                fade_ms = min(100, hard_cut_limit // 4)
                tts_audio = tts_audio[:hard_cut_limit].fade_out(fade_ms)
                logger.info(
                    f"Seg {idx}: cắt dự phòng xuống {hard_cut_limit}ms + fade-out {fade_ms}ms"
                )

            # Fade-in 50ms to prevent click noise at segment start
            if len(tts_audio) > 100:
                tts_audio = tts_audio.fade_in(50)

            # Overlay câu nói vào track chính tại ĐÚNG thời điểm gốc
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
    if burn_subtitles and srt_path and os.path.exists(srt_path):
        # We need to re-encode the video stream to apply filters
        # FFmpeg filter: drawbox to blur old subs at the bottom 10% area,
        # then subtitles filter to burn-in the new SRT.
        # Note: on Windows, backslashes in path must be escaped for subtitles filter.
        escaped_srt_path = srt_path.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"drawbox=y=ih-ih/10:w=iw:h=ih/10:color=black@0.7:t=fill,subtitles='{escaped_srt_path}'"
        
        cmd_video = [
            ffmpeg, "-y",
            "-i", video_path,
            "-i", temp_audio,
            "-vf", vf_filter,
            "-c:v", "libx264",     # Re-encode video stream
            "-preset", "superfast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_video_path
        ]
        logger.info(f"Re-encoding video with subtitle burn-in and drawbox mask: {vf_filter}")
    else:
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
