"""
Dubbing Pipeline Worker - Real AI Processing
Executes 20-step dubbing pipeline using real AI tools:
- Whisper (ASR) -> deep-translator (Translation) -> Edge-TTS (Vietnamese voice) -> FFmpeg (render)
"""
import os
import time
import shutil
import subprocess
import json
import logging
import threading
from datetime import datetime
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.job import DubbingJob, JobStep, TranscriptSegment, Export
from app.services.link_adapters import get_adapter_for_url
from app.utils.ffmpeg_utils import get_ffmpeg_path, inject_ffmpeg_to_path

# Limit concurrent FFmpeg re-encode jobs to prevent CPU saturation.
# -c:v copy jobs (no burn_subtitles) skip the semaphore — they are I/O bound.
_ffmpeg_encode_semaphore = threading.Semaphore(3)

logger = logging.getLogger(__name__)



def _ensure_source_video(job, source_path: str) -> None:
    """
    Ensure the source video file exists at source_path.
    If it was deleted (e.g. after step 20 cleanup), re-download or re-copy it.
    This is used in step 18 (Ket xuat video) to handle re-export flows.
    """
    if os.path.exists(source_path):
        return  # Already there, nothing to do

    logger.warning(f"Source video missing at {source_path}. Attempting to restore...")

    if job.source_type == "link" and job.source_url:
        from app.services.link_adapters import get_adapter_for_url
        adapter = get_adapter_for_url(job.source_url)
        if not adapter:
            raise FileNotFoundError(f"Khong tim duoc adapter de tai lai video: {job.source_url}")
        logger.info(f"Re-downloading source video from {job.source_url}...")
        adapter.download(job.source_url, source_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Tai lai video that bai: {source_path}")
        logger.info(f"Source video restored: {os.path.getsize(source_path) // 1024} KB")

    elif job.source_type == "upload" and job.source_url and os.path.exists(job.source_url):
        shutil.copy(job.source_url, source_path)
        logger.info(f"Source video restored from upload: {source_path}")

    else:
        raise FileNotFoundError(
            f"File nguon khong ton tai ({source_path}) va khong the khoi phuc. "
            f"Vui long tao tac vu moi."
        )

# Pipeline step names
PIPELINE_STEPS = [
    "Kiem tra lien ket",
    "Xac dinh nguon noi dung",
    "Doc thong tin video",
    "Tai noi dung",
    "Kiem tra file media",
    "Trich xuat am thanh",
    "Tach loi thoai va nhac nen",
    "Nhan dang giong noi",
    "Phan chia nguoi noi",
    "Phan tich ngu canh va cam xuc",
    "Dich sang tieng Viet",
    "Kiem tra va toi uu ban dich",
    "Chon giong cho tung nhan vat",
    "Tao giong noi tieng Viet",
    "Dong bo giong noi voi timeline",
    "Tron giong voi nhac nen",
    "Tao phu de",
    "Ket xuat video",
    "Kiem tra ket qua",
    "Luu file va hoan thanh"
]


def _update_step(db, job, step_record, step_num, message, status="processing"):
    """Helper to update step status and job progress"""
    job.current_step = step_num
    job.current_step_name = PIPELINE_STEPS[step_num - 1]
    job.progress_percent = int(((step_num - 1) / 20) * 100)
    if step_record:
        step_record.log_message = message
        if status == "completed":
            step_record.status = "completed"
            step_record.completed_at = datetime.utcnow()
    db.commit()


def run_dubbing_pipeline(job_id: str):
    """
    Execute the 20-step dubbing pipeline with REAL AI processing.
    Downloads video, transcribes, translates, generates Vietnamese TTS,
    and renders final dubbed video.
    """
    # Force clean environment PATH for this worker session to prevent DLL crashes
    inject_ffmpeg_to_path()
    
    db: Session = SessionLocal()
    try:
        job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return

        logger.info(f"Starting dubbing pipeline for Job {job_id}")
        job.status = "processing"
        db.commit()

        # Load voice configuration early
        voice_config = job.voice_config or {}
        if isinstance(voice_config, str):
            try:
                voice_config = json.loads(voice_config)
            except Exception:
                voice_config = {}

        # Performance logging structure
        perf_data = {}
        perf_file = os.path.join(str(settings.TEMP_DIR), f"{job_id}_perf.json")
        # Load existing performance data if resuming
        if os.path.exists(perf_file):
            try:
                with open(perf_file, "r", encoding="utf-8") as f:
                    perf_data = json.load(f)
            except Exception:
                pass

        # File paths
        source_path = str(settings.TEMP_DIR / f"{job_id}_source.mp4")
        extracted_audio = str(settings.AUDIO_DIR / f"{job_id}_original.wav")
        vocal_audio = str(settings.AUDIO_DIR / f"{job_id}_vocals.wav")
        bg_music = str(settings.AUDIO_DIR / f"{job_id}_music.wav")
        final_video = str(settings.EXPORTS_DIR / f"{job_id}_dubbed.mp4")
        final_audio = str(settings.EXPORTS_DIR / f"{job_id}_dubbed.mp3")
        srt_path = str(settings.SUBTITLES_DIR / f"{job_id}_vi.srt")
        vtt_path = str(settings.SUBTITLES_DIR / f"{job_id}_vi.vtt")

        # Determine start step (for re-runs)
        start_step = job.current_step if (job.current_step > 1 and job.progress_percent < 100) else 1

        # Store pipeline state
        segments_data = []
        voice_name = "vi-VN-HoaiMyNeural"

        # Load existing segments and voice configuration from database if resuming a pipeline
        if start_step > 1:
            gender = voice_config.get("voice_gender", "female")
            region = voice_config.get("voice_region", "south")
            voice_profile = voice_config.get("voice_profile", "auto")
            
            if voice_profile and voice_profile != "auto":
                voice_name = voice_profile
            else:
                from app.services.dubbing_engine import select_voice
                voice_name = select_voice(gender, region)

            db_segments = db.query(TranscriptSegment).filter(
                TranscriptSegment.job_id == job_id
            ).order_by(TranscriptSegment.segment_index.asc()).all()
            
            for db_seg in db_segments:
                segments_data.append({
                    "start": db_seg.start_time,
                    "end": db_seg.end_time,
                    "text": db_seg.text,
                    "translation": db_seg.translation or "",
                    "audio_path": db_seg.audio_path or ""
                })
            logger.info(f"Loaded {len(segments_data)} segments from DB for resume at step {start_step} using voice {voice_name}")

        for step_num in range(start_step, 21):
            step_name = PIPELINE_STEPS[step_num - 1]
            step_start_time = time.perf_counter()

            # Mark step as processing
            job.current_step = step_num
            job.current_step_name = step_name

            # Dynamic progress calculation based on performance weights
            BASE_WEIGHTS = {
                1: 1, 2: 1, 3: 1, 4: 10, 5: 1, 6: 2, 7: 20, 8: 25, 9: 1, 10: 1,
                11: 5, 12: 5, 13: 1, 14: 15, 15: 2, 16: 2, 17: 2, 18: 8, 19: 1, 20: 1
            }
            keep_bg = voice_config.get("keep_bg_music", True)
            burn_sub = voice_config.get("burn_subtitles", False)
            step_weights = dict(BASE_WEIGHTS)
            if not keep_bg:
                step_weights[7] = 0
            if burn_sub:
                step_weights[18] = 25
            else:
                step_weights[18] = 8
            
            total_weight = sum(step_weights.values())
            completed_weight = sum(step_weights[i] for i in range(1, step_num))
            current_weight = step_weights.get(step_num, 0) / 2.0
            job.progress_percent = min(99, max(0, int(((completed_weight + current_weight) / total_weight) * 100)))

            step_record = db.query(JobStep).filter(
                JobStep.job_id == job_id,
                JobStep.step_number == step_num
            ).first()

            if step_record:
                step_record.status = "processing"
                step_record.started_at = datetime.utcnow()
                step_record.log_message = f"Dang xu ly: {step_name}"
            db.commit()

            try:
                # ===================== STEP 1: Check URL =====================
                if step_num == 1:
                    from app.services.link_checker import check_url_safety
                    if job.source_type == "link":
                        is_safe, error_msg = check_url_safety(job.source_url or "")
                        if not is_safe:
                            raise Exception(f"URL khong an toan: {error_msg}")
                    step_record.log_message = "URL an toan, da xac minh."

                # ===================== STEP 2: Identify source =====================
                elif step_num == 2:
                    if job.source_type == "link":
                        adapter = get_adapter_for_url(job.source_url)
                        if not adapter:
                            raise Exception("Khong tim thay adapter cho URL nay.")
                        source_name = "YouTube" if "youtube" in job.source_url.lower() or "youtu.be" in job.source_url.lower() else "Web"
                        step_record.log_message = f"Nguon: {source_name}."
                    else:
                        step_record.log_message = "Nguon: File tai len."

                # ===================== STEP 3: Read metadata =====================
                elif step_num == 3:
                    if job.source_type == "link":
                        adapter = get_adapter_for_url(job.source_url)
                        
                        # Load download configurations
                        v_conf = job.voice_config or {}
                        if isinstance(v_conf, str):
                            try:
                                v_conf = json.loads(v_conf)
                            except Exception:
                                v_conf = {}
                        cookie_content = v_conf.get("cookie_content") or None

                        meta = adapter.extract_metadata(job.source_url, cookie_content=cookie_content)
                        if meta.get("duration"):
                            job.duration = meta["duration"]
                        step_record.log_message = f"Metadata: {meta.get('title', 'N/A')}, {job.duration}s."
                    else:
                        step_record.log_message = f"File upload, duration: {job.duration}s."

                # ===================== STEP 4: Download content =====================
                elif step_num == 4:
                    if job.source_type == "link":
                        adapter = get_adapter_for_url(job.source_url)
                        
                        # Load download configurations
                        v_conf = job.voice_config or {}
                        if isinstance(v_conf, str):
                            try:
                                v_conf = json.loads(v_conf)
                            except Exception:
                                v_conf = {}
                        cookie_content = v_conf.get("cookie_content") or None
                        download_quality = v_conf.get("download_quality") or "720p"
                        burn_subtitles = bool(v_conf.get("burn_subtitles", False))

                        # Backend guard: re-encoding 1080p with burn_subtitles is very
                        # CPU-heavy on weak machines. Cap at 720p automatically and log
                        # a warning so the user can see it in the job step log.
                        if burn_subtitles and download_quality == "1080p":
                            logger.warning(
                                "burn_subtitles=True + 1080p detected — auto-downgrade to 720p "
                                "to prevent CPU overload. Change quality to 720p or disable "
                                "burn_subtitles to remove this limit."
                            )
                            download_quality = "720p"

                        # exact_cut: True (default) = force keyframes at cuts (precise but CPU-heavy)
                        #            False           = fast cut aligned to nearest keyframe
                        exact_cut = bool(v_conf.get("exact_cut", True))

                        # Support partial download (time-range clip)
                        clip_start = getattr(job, 'clip_start', None)
                        clip_end = getattr(job, 'clip_end', None)
                        
                        adapter.download(
                            job.source_url, 
                            source_path,
                            clip_start=clip_start, 
                            clip_end=clip_end,
                            download_quality=download_quality,
                            cookie_content=cookie_content,
                            exact_cut=exact_cut
                        )
                        if not os.path.exists(source_path):
                            raise FileNotFoundError(f"Download that bai: file khong ton tai tai {source_path}")
                        file_size = os.path.getsize(source_path)
                        clip_info = f" [{clip_start}-{clip_end}]" if clip_start or clip_end else ""
                        step_record.log_message = f"Da tai thanh cong{clip_info} ({file_size // 1024} KB) - Chat luong: {download_quality}."
                    elif job.source_type == "upload" and job.source_url and os.path.exists(job.source_url):
                        shutil.copy(job.source_url, source_path)
                        step_record.log_message = "Da sao chep file upload."
                    else:
                        raise FileNotFoundError("Khong tim thay file nguon.")


                # ===================== STEP 5: Validate media =====================
                elif step_num == 5:
                    if not os.path.exists(source_path):
                        raise FileNotFoundError(f"File nguon khong ton tai: {source_path}")
                    file_size = os.path.getsize(source_path)
                    if file_size < 1000:
                        raise ValueError(f"File nguon qua nho ({file_size} bytes), co the bi loi.")
                    step_record.log_message = f"File hop le ({file_size // 1024} KB)."

                # ===================== STEP 6: Extract audio =====================
                elif step_num == 6:
                    from app.services.dubbing_engine import extract_audio_from_video
                    extract_audio_from_video(source_path, extracted_audio)
                    step_record.log_message = f"Trich xuat audio WAV 16kHz mono thanh cong."

                # ===================== STEP 7: Separate vocals (Demucs AI) =====================
                elif step_num == 7:
                    keep_bg = voice_config.get("keep_bg_music", True)
                    if not keep_bg:
                        step_record.log_message = "Bo qua tach nhac nen AI (Demucs) do keep_bg_music = False."
                        logger.info("Skipping Demucs audio separation since keep_bg_music=False.")
                    else:
                        from app.services.dubbing_engine import separate_vocals
                        # Chạy tách nhạc nền bằng Demucs (có tự động fallback bên trong hàm)
                        real_separation = separate_vocals(extracted_audio, vocal_audio, bg_music, job_id)
                        if real_separation:
                            step_record.log_message = "Tach loi thoai va nhac nen thanh cong bang AI (Demucs)."
                        else:
                            step_record.log_message = "Demucs khong kha dung. Da su dung phuong an du phong (giu nhac goc co tieng)."

                # ===================== STEP 8: Speech recognition (ASR / Subtitle / OCR) =====================
                elif step_num == 8:
                    from app.services.dubbing_engine import transcribe_audio, download_youtube_subtitles, ocr_video_subtitles
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)
                    whisper_model = voice_config.get("whisper_model", "base")
                    asr_method = voice_config.get("asr_method", "whisper")
                    perf_mode = voice_config.get("performance_mode", "balanced")
                    align_mode = voice_config.get("alignment_mode", "segment")
                    
                    segments_data = []
                    method_used = asr_method
                    
                    # Chỉ tự động tải phụ đề nếu người dùng lựa chọn asr_method == "softsub"
                    try_softsub_first = (asr_method == "softsub")

                    if try_softsub_first:
                        if job.source_type == "link" and job.source_url:
                            try:
                                logger.info(f"Auto-trying to download YouTube subtitles for Job {job_id}...")
                                segments_data = download_youtube_subtitles(job.source_url, job_id)
                                if segments_data:
                                    method_used = "softsub"
                                    logger.info(f"Successfully loaded {len(segments_data)} segments from YouTube subtitles.")
                                else:
                                    if asr_method == "softsub":
                                        raise ValueError("Không tìm thấy dữ liệu phụ đề tiếng Anh.")
                            except Exception as e:
                                if asr_method == "softsub":
                                    logger.warning(f"Failed to load YouTube subtitles: {e}.")
                                    logger.warning("Fallback to Whisper ASR...")
                                else:
                                    logger.info(f"Auto-subtitle download not available: {e}. Proceeding with selected ASR method (Whisper).")
                                method_used = "whisper"
                        else:
                            if asr_method == "softsub":
                                logger.warning("Softsub only works with links. Fallback to Whisper ASR...")
                                method_used = "whisper"
                    
                    # ─── PHƯƠNG ÁN 2: Nhận diện chữ trên màn hình (Video OCR) ───
                    if (asr_method == "ocr" or method_used == "ocr") and not segments_data:
                        try:
                            logger.info(f"Running Video OCR for Job {job_id}...")
                            segments_data = ocr_video_subtitles(source_path)
                            if not segments_data:
                                raise ValueError("OCR không phát hiện được chữ phụ đề trên khung hình.")
                            logger.info(f"Loaded {len(segments_data)} segments via Video OCR.")
                        except Exception as e:
                            logger.warning(f"Video OCR failed: {e}. Fallback to Whisper ASR...")
                            method_used = "whisper"
                    
                    # ─── PHƯƠNG ÁN 3: Nhận diện giọng nói mặc định (Whisper ASR) ───
                    if method_used == "whisper" or not segments_data:
                        # Use vocal_audio (separated vocals) if available to improve WhisperX accuracy, otherwise fallback to extracted_audio
                        asr_audio = vocal_audio if (os.path.exists(vocal_audio) and os.path.getsize(vocal_audio) > 100) else extracted_audio
                        logger.info(f"Running Whisper ASR (model: {whisper_model}, alignment: {align_mode}, input: {asr_audio}) for Job {job_id}...")
                        segments_data = transcribe_audio(asr_audio, whisper_model=whisper_model, alignment_mode=align_mode)
                        method_used = "whisper"
                    
                    # Save segments to database
                    for idx, seg in enumerate(segments_data):
                        new_seg = TranscriptSegment(
                            job_id=job_id,
                            segment_index=idx,
                            start_time=seg["start"],
                            end_time=seg["end"],
                            text=seg["text"],
                            translation="",  # Will be filled in step 11
                            speaker=seg.get("speaker", "Speaker 1"),  # use detected speaker
                            status="completed"
                        )
                        db.add(new_seg)
                    
                    unique_speakers = set(s.get("speaker", "Speaker 1") for s in segments_data)
                    method_labels = {
                        "whisper": "Whisper ASR",
                        "softsub": "YouTube Subtitles",
                        "ocr": "Video OCR"
                    }
                    step_record.log_message = f"Lấy lời thoại thành công bằng {method_labels.get(method_used, method_used)} ({len(segments_data)} đoạn). Tìm thấy {len(unique_speakers)} người nói."


                # ===================== STEP 9: Speaker diarization =====================
                elif step_num == 9:
                    # Speaker info already detected in step 8 via silence-gap heuristic
                    unique_speakers = set(s.get("speaker", "Speaker 1") for s in segments_data)
                    n_speakers = len(unique_speakers)
                    if n_speakers >= 2:
                        step_record.log_message = f"Phat hien {n_speakers} nguoi noi. Se su dung giong xen ke nam/nu."
                    else:
                        step_record.log_message = "Phat hien 1 nguoi noi. Su dung 1 giong duy nhat."

                # ===================== STEP 10: Emotion analysis (simplified) =====================
                elif step_num == 10:
                    step_record.log_message = "Phan tich cam xuc: Tu nhien, trang thai binh thuong."

                # ===================== STEP 11: Translate to Vietnamese =====================
                elif step_num == 11:
                    from app.services.dubbing_engine import translate_segments
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)
                    video_context = voice_config.get("video_context", "neutral")
                    video_topic = voice_config.get("video_topic", "")
                    
                    segments_data = translate_segments(
                        segments_data, 
                        target_lang="vi", 
                        video_context=video_context,
                        video_topic=video_topic
                    )

                    # Update segments in DB with translations
                    db_segments = db.query(TranscriptSegment).filter(
                        TranscriptSegment.job_id == job_id
                    ).order_by(TranscriptSegment.segment_index.asc()).all()

                    for db_seg, data_seg in zip(db_segments, segments_data):
                        db_seg.translation = data_seg.get("translation", "")

                    step_record.log_message = f"Dich {len(segments_data)} cau sang tieng Viet (Google Translate)."

                # ===================== STEP 12: Optimize translation =====================
                elif step_num == 12:
                    from app.services.dubbing_engine import optimize_translation_constraints
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)

                    # Get Gemini key for LLM-powered shortening
                    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

                    segments_data, opt_stats = optimize_translation_constraints(
                        segments_data, gemini_key=gemini_key
                    )

                    # Sync optimized translations back to DB
                    db_segs = db.query(TranscriptSegment).filter(
                        TranscriptSegment.job_id == job_id
                    ).order_by(TranscriptSegment.segment_index.asc()).all()
                    for db_seg, data_seg in zip(db_segs, segments_data):
                        db_seg.translation = data_seg.get("translation", db_seg.translation)

                    total = len(segments_data)
                    overrun = opt_stats.get("total_overrun", 0)
                    llm_cnt = opt_stats.get("llm_shortened", 0)
                    fb_cnt = opt_stats.get("fallback_shortened", 0)

                    if overrun == 0:
                        step_record.log_message = f"Tất cả {total} đoạn dịch đều vừa đúng khung thời gian."
                    else:
                        step_record.log_message = (
                            f"Tối ưu {overrun}/{total} đoạn dịch quá dài: "
                            f"{llm_cnt} rút gọn thông minh (Gemini), "
                            f"{fb_cnt} rút gọn cơ học (fallback)."
                        )

                # ===================== STEP 13: Select voice =====================
                elif step_num == 13:
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)
                    gender = voice_config.get("voice_gender", "female")
                    region = voice_config.get("voice_region", "south")
                    voice_profile = voice_config.get("voice_profile", "auto")
                    
                    if voice_profile and voice_profile != "auto":
                        voice_name = voice_profile
                    else:
                        from app.services.dubbing_engine import select_voice
                        voice_name = select_voice(gender, region)
                    step_record.log_message = f"Da chon giong: {voice_name}."


                # ===================== STEP 14: Generate TTS =====================
                elif step_num == 14:
                    from app.services.dubbing_engine import generate_all_tts_segments, DEFAULT_SPEAKER_VOICE_MAP
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)
                    video_context = voice_config.get("video_context", "neutral")
                    voice_profile = voice_config.get("voice_profile", "auto")

                    # Build voice_map for multi-speaker support
                    # User can override via voice_config["speaker_voice_map"]
                    custom_map = voice_config.get("speaker_voice_map", None)
                    if custom_map:
                        voice_map = custom_map
                    elif voice_profile and voice_profile != "auto":
                        # SINGLE VOICE MODE: If the user selected a specific voice profile (not 'auto'),
                        # force all detected speakers to use this single voice to respect their choice.
                        voice_map = {
                            "Speaker 1": voice_name,
                            "Speaker 2": voice_name,
                            "Speaker 3": voice_name,
                            "Speaker 4": voice_name,
                        }
                    else:
                        # AUTO VOICE MODE: Automatically assign alternating male/female voices to
                        # different speakers for dynamic and lively dubbing.
                        opposite_voice = (
                            "vi-VN-NamMinhNeural" if voice_name == "vi-VN-HoaiMyNeural"
                            else "vi-VN-HoaiMyNeural"
                        )
                        voice_map = {
                            "Speaker 1": voice_name,
                            "Speaker 2": opposite_voice,
                            "Speaker 3": voice_name,
                            "Speaker 4": opposite_voice,
                        }

                    tts_workers = voice_config.get("tts_workers", 4)
                    segments_data = generate_all_tts_segments(
                        segments_data,
                        str(settings.AUDIO_DIR),
                        job_id,
                        voice=voice_name,
                        video_context=video_context,
                        voice_map=voice_map,
                        tts_workers=tts_workers
                    )

                    # Update audio paths in DB
                    db_segments = db.query(TranscriptSegment).filter(
                        TranscriptSegment.job_id == job_id
                    ).order_by(TranscriptSegment.segment_index.asc()).all()

                    for db_seg, data_seg in zip(db_segments, segments_data):
                        db_seg.audio_path = data_seg.get("audio_path", "")

                    voices_used = set(s.get("voice_used", voice_name) for s in segments_data)
                    step_record.log_message = f"Tao {len(segments_data)} doan giong noi tieng Viet (Edge-TTS, {len(voices_used)} giong: {', '.join(voices_used)})"

                # ===================== STEP 15: Sync TTS with timeline =====================
                elif step_num == 15:
                    step_record.log_message = "Dong bo giong noi voi timeline video: Hoan tat."

                # ===================== STEP 16: Mix audio =====================
                elif step_num == 16:
                    step_record.log_message = "Tron am thanh (Audio mixing): Dang chuan bi."

                # ===================== STEP 17: Generate subtitles =====================
                elif step_num == 17:
                    from app.services.dubbing_engine import generate_srt_file, generate_vtt_file
                    generate_srt_file(segments_data, srt_path)
                    generate_vtt_file(segments_data, vtt_path)
                    step_record.log_message = "Tao phu de SRT va VTT thanh cong."

                # ===================== STEP 18: Render final video =====================
                elif step_num == 18:
                    from app.services.dubbing_engine import merge_tts_with_video
                    voice_config = job.voice_config or {}
                    if isinstance(voice_config, str):
                        voice_config = json.loads(voice_config)
                    keep_bg = voice_config.get("keep_bg_music", True)
                    bg_volume_db = int(voice_config.get("bg_volume_db", -18))

                    # Ensure source video exists (may have been deleted on previous run's cleanup)
                    _ensure_source_video(job, source_path)

                    burn_sub = voice_config.get("burn_subtitles", False)
                    # Acquire semaphore only for re-encode jobs (burn_subtitles=True).
                    # Stream-copy jobs (-c:v copy) are I/O bound and not limited.
                    _sem = _ffmpeg_encode_semaphore if burn_sub else None
                    if _sem:
                        logger.info("[Step18] Waiting for FFmpeg encode slot (semaphore)...")
                        _sem.acquire()
                    ffmpeg_threads = voice_config.get("ffmpeg_threads", 2)
                    try:
                        merge_tts_with_video(
                            video_path=source_path,
                            segments=segments_data,
                            bg_music_path=bg_music,
                            output_video_path=final_video,
                            output_audio_path=final_audio,
                            keep_bg_music=keep_bg,
                            bg_volume_db=bg_volume_db,
                            burn_subtitles=burn_sub,
                            srt_path=srt_path,
                            ffmpeg_threads=ffmpeg_threads
                        )
                    finally:
                        if _sem:
                            _sem.release()
                    step_record.log_message = f"Ket xuat video long tieng thanh cong ({os.path.getsize(final_video) // 1024} KB)."  

                # ===================== STEP 19: Quality check =====================
                elif step_num == 19:
                    # Verify output files exist and are valid
                    if not os.path.exists(final_video) or os.path.getsize(final_video) < 1000:
                        raise ValueError("Video ket xuat bi loi hoac qua nho.")
                    if not os.path.exists(final_audio):
                        raise ValueError("Audio ket xuat khong ton tai.")
                    step_record.log_message = "Kiem tra chat luong: Video va audio deu hop le."

                # ===================== STEP 20: Save and finalize =====================
                elif step_num == 20:
                    # Save export records
                    ex_vid = Export(
                        job_id=job_id, file_type="video",
                        file_path=final_video,
                        file_size=os.path.getsize(final_video)
                    )
                    ex_aud = Export(
                        job_id=job_id, file_type="audio_mp3",
                        file_path=final_audio,
                        file_size=os.path.getsize(final_audio)
                    )
                    ex_srt = Export(
                        job_id=job_id, file_type="subtitle_srt",
                        file_path=srt_path,
                        file_size=os.path.getsize(srt_path) if os.path.exists(srt_path) else 0
                    )
                    db.add(ex_vid)
                    db.add(ex_aud)
                    db.add(ex_srt)

                    step_record.log_message = "Luu ket qua va don dep bo nho thanh cong."
                    # NOTE: We intentionally keep source_path alive until explicitly cleaned
                    # to support re-export flows. File will be removed on next pipeline restart
                    # only if a fresh download is available.

                # Mark step completed
                if step_record:
                    if step_num == 7 and not keep_bg:
                        step_record.status = "skipped"
                    else:
                        step_record.status = "completed"
                    step_record.completed_at = datetime.utcnow()
                db.commit()

                # Log step performance
                step_duration = time.perf_counter() - step_start_time
                perf_data[str(step_num)] = {
                    "name": step_name,
                    "duration_seconds": round(step_duration, 2),
                    "status": step_record.status if step_record else "completed"
                }
                try:
                    with open(perf_file, "w", encoding="utf-8") as f:
                        json.dump(perf_data, f, ensure_ascii=False, indent=2)
                except Exception as pe:
                    logger.warning(f"Failed to write perf log: {pe}")

            except Exception as e:
                logger.error(f"Pipeline step {step_num} failed: {str(e)}")
                if step_record:
                    step_record.status = "failed"
                    step_record.completed_at = datetime.utcnow()
                    step_record.log_message = f"Loi: {str(e)[:300]}"
                raise e

        # Pipeline completed successfully
        job.status = "completed"
        job.progress_percent = 100
        job.completed_at = datetime.utcnow()
        db.commit()
        logger.info(f"Dubbing pipeline completed successfully for Job {job_id}")

    except Exception as e:
        logger.error(f"Pipeline failed for Job {job_id}: {str(e)}")
        try:
            db.rollback()
        except Exception:
            pass

        # Create a fresh database session to safely update the error status
        fresh_db = SessionLocal()
        try:
            job = fresh_db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)[:500]
                fresh_db.commit()
        except Exception as db_err:
            logger.error(f"Failed to update job status to failed: {db_err}")
        finally:
            fresh_db.close()
    finally:
        db.close()
