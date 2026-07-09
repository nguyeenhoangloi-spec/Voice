import os
import uuid
import shutil
import json
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.config import settings
from app.database import get_db
from app.dependencies import templates, get_current_user
from app.models.job import DubbingJob, JobStep, TranscriptSegment, Export
from app.schemas.job import LinkCheckRequest, JobCreateRequest, TimelineEditRequest
from app.services.link_checker import check_url_safety
from app.services.link_adapters import get_adapter_for_url
from app.services.media_probe import probe_media_file

router = APIRouter()
logger = logging.getLogger(__name__)

# Danh sách 20 giai đoạn lồng tiếng bắt buộc
PIPELINE_STEPS = [
    "Kiểm tra liên kết",
    "Xác định nguồn nội dung",
    "Đọc thông tin video",
    "Tải nội dung",
    "Kiểm tra file media",
    "Trích xuất âm thanh",
    "Tách lời thoại và nhạc nền",
    "Nhận dạng giọng nói",
    "Phân chia người nói",
    "Phân tích ngữ cảnh và cảm xúc",
    "Dịch sang tiếng Việt",
    "Kiểm tra và tối ưu bản dịch",
    "Chọn giọng cho từng nhân vật",
    "Tạo giọng nói tiếng Việt",
    "Đồng bộ giọng nói với timeline",
    "Trộn giọng với nhạc nền",
    "Tạo phụ đề",
    "Kết xuất video",
    "Kiểm tra kết quả",
    "Lưu file và hoàn thành"
]

@router.get("/create", response_class=HTMLResponse)
def get_create_job_page(request: Request, user=Depends(get_current_user)):
    """Render trang Tạo tác vụ lồng tiếng mới"""
    return templates.TemplateResponse(
        "user/create_job.html",
        {
            "request": request,
            "user": user,
            "page_title": "Tạo tác vụ lồng tiếng - VoiceAI"
        }
    )

@router.post("/check-link")
def api_check_link(req: LinkCheckRequest, user=Depends(get_current_user)):
    """API kiểm tra an toàn URL và trích xuất thông tin sơ bộ (Metadata)"""
    url = req.url
    
    # 1. Kiểm tra an toàn chống SSRF
    is_safe, error_msg = check_url_safety(url)
    if not is_safe:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": error_msg}
        )
        
    # 2. Tìm adapter phù hợp
    adapter = get_adapter_for_url(url)
    if not adapter:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "Liên kết này không được hỗ trợ bởi hệ thống adapter hiện tại."}
        )
        
    # 3. Trích xuất metadata
    meta = adapter.extract_metadata(url)
    if not meta.get("success"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": meta.get("error")}
        )
        
    return {"success": True, "data": meta}

@router.post("/upload")
def api_upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    """API xử lý tải lên file video/audio cục bộ"""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in [".mp4", ".webm", ".mp3", ".wav", ".ogg", ".aac", ".m4a"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Định dạng tệp tin không được hỗ trợ."
        )
        
    temp_path = settings.UPLOADS_DIR / f"{file_id}{file_ext}"
    
    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_size = os.path.getsize(temp_path)
        if file_size > max_bytes:
            os.remove(temp_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Kích thước tệp tin vượt quá giới hạn {settings.MAX_UPLOAD_SIZE_MB} MB."
            )
            
        probe_meta = probe_media_file(str(temp_path))
        
        max_duration = settings.MAX_VIDEO_DURATION_MINUTES * 60
        if probe_meta.get("duration", 0.0) > max_duration:
            os.remove(temp_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Thời lượng tệp tin vượt quá giới hạn {settings.MAX_VIDEO_DURATION_MINUTES} phút."
            )
            
        return {
            "success": True,
            "filename": file.filename,
            "filepath": str(temp_path),
            "file_size": file_size,
            "duration": probe_meta.get("duration", 0.0),
            "has_video": probe_meta.get("has_video", False)
        }
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi khi xử lý file tải lên: {str(e)}"
        )

@router.post("/create")
def api_create_job(
    req: JobCreateRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """API lưu tác vụ lồng tiếng và kích hoạt pipeline xử lý ngầm"""
    job_id = str(uuid.uuid4())
    
    voice_config = {
        "voice_gender": req.voice_gender,
        "voice_region": req.voice_region,
        "voice_profile": req.voice_profile or "auto",
        "voice_emotion": req.voice_emotion,
        "keep_bg_music": req.keep_bg_music,
        "bg_volume_db": req.bg_volume_db if req.bg_volume_db is not None else -18,
        "generate_subtitles": req.generate_subtitles,
        "burn_subtitles": req.burn_subtitles or False,
        "translation_mode": req.translation_mode,
        "video_context": req.video_context or "neutral",
        "video_topic": req.video_topic or "",
        "whisper_model": req.whisper_model or "base",
        "asr_method": req.asr_method or "whisper"
    }
    
    new_job = DubbingJob(
        id=job_id,
        user_id=user.id,
        source_url=req.source_url,
        source_type=req.source_type,
        status="pending",
        progress_percent=0,
        current_step=1,
        current_step_name=PIPELINE_STEPS[0],
        duration=req.duration,
        voice_config=voice_config
    )
    db.add(new_job)
    
    for idx, name in enumerate(PIPELINE_STEPS):
        new_step = JobStep(
            job_id=job_id,
            step_number=idx + 1,
            name=name,
            status="pending" if idx > 0 else "processing",
            started_at=datetime.utcnow() if idx == 0 else None
        )
        db.add(new_step)
        
    db.commit()

    from app.workers.dubbing_tasks import run_dubbing_pipeline
    background_tasks.add_task(run_dubbing_pipeline, job_id)
    
    return {
        "success": True,
        "job_id": job_id,
        "message": "Tác vụ đã được khởi tạo và đang chạy ngầm."
    }

@router.get("/job/{job_id}", response_class=HTMLResponse)
def get_job_progress_page(request: Request, job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Render trang chi tiết theo dõi tiến trình 20 bước của tác vụ lồng tiếng"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id, DubbingJob.user_id == user.id).first()
    if not job:
        if user.role == "admin":
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
            
    steps = db.query(JobStep).filter(JobStep.job_id == job_id).order_by(JobStep.step_number.asc()).all()
    
    return templates.TemplateResponse(
        "user/job_progress.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "steps": steps,
            "page_title": f"Tiến trình lồng tiếng {job_id[:8]} - VoiceAI"
        }
    )

@router.get("/job/{job_id}/status")
def get_job_status_json(job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """API trả về JSON trạng thái tiến trình để Client gọi ajax/polling hoặc WebSocket sync"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
        
    if job.user_id != user.id and user.role != "admin":
        return JSONResponse(status_code=403, content={"error": "Permission denied"})
        
    steps = db.query(JobStep).filter(JobStep.job_id == job_id).order_by(JobStep.step_number.asc()).all()
    
    steps_data = []
    for s in steps:
        steps_data.append({
            "step_number": s.step_number,
            "name": s.name,
            "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            "log_message": s.log_message
        })
        
    segments = db.query(TranscriptSegment).filter(TranscriptSegment.job_id == job_id).order_by(TranscriptSegment.segment_index.asc()).all()
    segments_data = []
    for seg in segments:
        segments_data.append({
            "id": seg.id,
            "segment_index": seg.segment_index,
            "start_time": seg.start_time,
            "end_time": seg.end_time,
            "speaker": seg.speaker,
            "text": seg.text,
            "translation": seg.translation,
            "emotional_tag": seg.emotional_tag,
            "audio_path": f"/storage/audio/{os.path.basename(seg.audio_path)}" if seg.audio_path else None
        })

    exports = db.query(Export).filter(Export.job_id == job_id).all()
    exports_data = []
    for exp in exports:
        exports_data.append({
            "file_type": exp.file_type,
            "file_path": f"/storage/exports/{os.path.basename(exp.file_path)}"
        })

    return {
        "job_id": job.id,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "current_step": job.current_step,
        "current_step_name": job.current_step_name,
        "error_message": job.error_message,
        "steps": steps_data,
        "segments": segments_data,
        "exports": exports_data
    }

@router.get("/job/{job_id}/events")
def stream_job_events(job_id: str, user=Depends(get_current_user)):
    """Server-Sent Events (SSE) stream để cập nhật tiến trình thời gian thực mà không tốn tài nguyên polling"""
    from app.database import SessionLocal
    
    async def event_generator():
        while True:
            db = SessionLocal()
            try:
                job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
                if not job:
                    yield "data: {\"error\": \"Not found\"}\n\n"
                    break
                    
                if job.user_id != user.id and user.role != "admin":
                    yield "data: {\"error\": \"Permission denied\"}\n\n"
                    break
                    
                status_data = {
                    "status": job.status,
                    "progress_percent": job.progress_percent,
                    "current_step": job.current_step,
                    "current_step_name": job.current_step_name,
                    "error_message": job.error_message
                }
                yield f"data: {json.dumps(status_data)}\n\n"
                
                if job.status in ["completed", "failed"]:
                    break
            finally:
                db.close()
            await asyncio.sleep(1.0)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/job/{job_id}/edit", response_class=HTMLResponse)
def get_timeline_editor_page(request: Request, job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Render giao diện trình chỉnh sửa dòng thời gian (Timeline Editor)"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id, DubbingJob.user_id == user.id).first()
    if not job:
        if user.role == "admin":
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
            
    segments = db.query(TranscriptSegment).filter(TranscriptSegment.job_id == job_id).order_by(TranscriptSegment.segment_index.asc()).all()
    
    return templates.TemplateResponse(
        "user/timeline_editor.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "segments": segments,
            "page_title": f"Chỉnh sửa Timeline {job_id[:8]} - VoiceAI"
        }
    )

@router.post("/job/{job_id}/edit")
def api_save_timeline_edit(
    job_id: str,
    req: TimelineEditRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """API lưu trữ các thay đổi bản dịch/timeline và chạy lại pipeline kết xuất từ bước 15"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id, DubbingJob.user_id == user.id).first()
    if not job:
        if user.role == "admin":
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            return JSONResponse(status_code=404, content={"success": False, "error": "Không tìm thấy tác vụ."})
            
    for seg_data in req.segments:
        seg = db.query(TranscriptSegment).filter(
            TranscriptSegment.id == seg_data.id, 
            TranscriptSegment.job_id == job_id
        ).first()
        if seg:
            seg.start_time = seg_data.start_time
            seg.end_time = seg_data.end_time
            seg.text = seg_data.text
            seg.translation = seg_data.translation
            seg.speaker = seg_data.speaker
            seg.emotional_tag = seg_data.emotional_tag
            
    job.status = "pending"
    job.progress_percent = 65
    job.current_step = 14
    job.current_step_name = PIPELINE_STEPS[13]
    job.completed_at = None
    
    steps = db.query(JobStep).filter(JobStep.job_id == job_id).all()
    for s in steps:
        if s.step_number >= 14:
            s.status = "pending"
            s.started_at = None
            s.completed_at = None
            s.log_message = "Chờ kết xuất lại sau khi lưu chỉnh sửa."
            
    db.commit()
    
    from app.workers.dubbing_tasks import run_dubbing_pipeline
    background_tasks.add_task(run_dubbing_pipeline, job_id)
    
    return {
        "success": True,
        "message": "Các chỉnh sửa đã được áp dụng. Hệ thống đang tiến hành kết xuất lại video."
    }

@router.get("/history", response_class=HTMLResponse)
def get_history_page(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Render trang lịch sử tác vụ lồng tiếng"""
    jobs = db.query(DubbingJob).filter(DubbingJob.user_id == user.id).order_by(DubbingJob.created_at.desc()).all()
    return templates.TemplateResponse(
        "user/history.html",
        {
            "request": request,
            "user": user,
            "jobs": jobs,
            "page_title": "Lịch sử lồng tiếng - VoiceAI"
        }
    )

@router.get("/voices", response_class=HTMLResponse)
def get_voices_page(request: Request, user=Depends(get_current_user)):
    """Render danh sách mẫu giọng AI hệ thống (Tải nhanh, không bị blocking)"""
    from app.services.kokoro_service import KOKORO_VOICES
    from app.services.tiktok_service import TIKTOK_VOICES
    
    voices = [
        {
            "id": "hoaimy",
            "name": "Microsoft Edge Nữ (Hoài My - Neural)",
            "gender": "Nữ",
            "region": "Việt Nam (Edge TTS)",
            "voice": "vi-VN-HoaiMyNeural",
            "desc": "Giọng nữ đọc trong trẻo, tự nhiên, cực kỳ phù hợp thuyết minh phim, bài giảng hoặc sách nói."
        },
        {
            "id": "namminh",
            "name": "Microsoft Edge Nam (Nam Minh - Neural)",
            "gender": "Nam",
            "region": "Việt Nam (Edge TTS)",
            "voice": "vi-VN-NamMinhNeural",
            "desc": "Giọng nam đọc trầm ấm, rõ ràng, thích hợp làm tin tức, phóng sự và tài liệu kỹ thuật."
        }
    ]
    
    # Thêm các giọng TikTok/CapCut nổi tiếng
    for v in TIKTOK_VOICES:
        voices.append({
            "id": v["id"],
            "name": v["name"],
            "gender": "Nữ" if v["gender"] == "female" else "Nam",
            "region": "CapCut / TikTok (Free)",
            "voice": v["id"],
            "desc": v["desc"]
        })
    
    region_names = {
        "en": "Mỹ / Anh (English)",
        "es": "Tây Ban Nha (Spanish)",
        "fr": "Pháp (French)",
        "hi": "Ấn Độ (Hindi)",
        "it": "Ý (Italian)",
        "pt": "Bồ Đào Nha (Portuguese)",
        "ja": "Nhật Bản (Japanese)",
        "zh": "Trung Quốc (Chinese)"
    }
    
    for lang, voice_list in KOKORO_VOICES.items():
        region_name = region_names.get(lang, lang.upper())
        for v in voice_list:
            voices.append({
                "id": v["id"],
                "name": f"Kokoro {v['name']}",
                "gender": "Nữ" if v["gender"] == "female" else "Nam",
                "region": f"{region_name} (Kokoro)",
                "voice": v["id"],
                "desc": f"Giọng đọc {v['gender']} chất lượng phòng thu, chạy offline hoàn toàn. Ngôn ngữ gốc: {region_name}."
            })
                 
    return templates.TemplateResponse(
        "user/voices.html",
        {
            "request": request,
            "user": user,
            "voices": voices,
            "page_title": "Mẫu giọng AI lồng tiếng - VoiceAI"
        }
    )


@router.get("/voices/sample/{voice_id}.mp3")
def get_voice_sample_audio(voice_id: str):
    """Sinh động (Lazy Loading) âm thanh mẫu của giọng AI và trả về dưới dạng file stream"""
    from app.config import settings
    from app.services.dubbing_engine import generate_tts_audio
    from fastapi.responses import FileResponse
    
    sample_dir = settings.STORAGE_DIR / "samples"
    os.makedirs(sample_dir, exist_ok=True)
    
    # We save as .wav for Kokoro, .mp3 for others
    if voice_id.startswith(("af_", "am_", "bf_", "bm_", "ef_", "em_", "ff_", "hf_", "hm_", "if_", "im_", "pf_", "pm_", "jf_", "jm_", "zf_")):
        file_path = sample_dir / f"{voice_id}.wav"
    else:
        file_path = sample_dir / f"{voice_id}.mp3"
    
    if not file_path.exists() or file_path.stat().st_size == 0:
        sample_text = "Xin chào! Đây là bản nghe thử giọng đọc chất lượng phòng thu của hệ thống Voice AI."
        voice_code = voice_id
        
        if voice_id == "hoaimy":
            voice_code = "vi-VN-HoaiMyNeural"
            sample_text = "Xin chào! Tôi là giọng đọc trí tuệ nhân tạo Hoài My, mang chất âm tiếng Việt trong trẻo, chuyên nghiệp và đầy tự nhiên. Tôi rất phù hợp để thuyết minh bài giảng, review phim hoặc lồng tiếng các nội dung giáo dục. Hãy cùng tôi tạo nên những video thật cuốn hút nhé!"
        elif voice_id == "namminh":
            voice_code = "vi-VN-NamMinhNeural"
            sample_text = "Chào bạn! Tôi là Nam Minh, giọng đọc Nam của hệ thống Voice AI. Với tông giọng trầm ấm, rõ ràng và mạch lạc, tôi rất thích hợp cho các nội dung tin tức, phóng sự hoặc đọc tài liệu kỹ thuật. Rất hân hạnh được đồng hành cùng dự án của bạn."
        elif voice_id == "vi_vn_002":
            sample_text = "Xin chào các bạn! Đây là giọng nữ hoạt ngôn cực kỳ quen thuộc trên CapCut và TikTok. Giọng nói của mình rất năng động, vui tươi, thích hợp cho các video ngắn xu hướng, vlog đời sống và review ăn uống. Hãy dùng thử giọng của mình nhé!"
        elif voice_id == "vi_vn_001":
            sample_text = "Chào mọi người! Đây là giọng nam trầm ấm của CapCut. Mình chuyên dùng để lồng tiếng cho các video kể chuyện, review phim hoặc đọc tin tức hàng ngày. Chất giọng tự nhiên và mạch lạc sẽ giúp video của bạn thu hút hơn rất nhiều."
        elif voice_id.startswith("en_us_") and voice_id != "en_us_ghostface":
            sample_text = "Hi! This is a popular CapCut text-to-speech voice. I can read your English scripts with a natural and engaging tone. Let's make some amazing videos together!"
        elif voice_id == "en_us_ghostface":
            sample_text = "Wazzzup! Yes, I am the Ghostface from the Scream movie. You think you can escape me? I am right behind you! Happy Halloween."
        elif voice_id.startswith(("af_", "am_", "bf_", "bm_")):
            sample_text = "Hello! I am a high-quality speech synthesis voice from Kokoro AI. I run completely offline with studio-like clarity. I am ready to read your text now."
        elif voice_id.startswith(("ef_", "em_")):
            sample_text = "¡Hola! Soy una voz de síntesis de voz de alta calidad de Kokoro AI, que se ejecuta completamente fuera de línea con claridad de estudio."
        elif voice_id.startswith("ff_"):
            sample_text = "Bonjour! Je suis une voix de synthèse vocale de haut        try:
            generate_tts_audio(
                text=sample_text,
                output_path=str(file_path),
                voice=voice_code
            )
        except Exception as e:
            logger.warning(f"Lỗi khi sinh giọng mẫu {voice_id}: {e}. Tiến hành fallback sang Edge TTS.")
            try:
                import edge_tts
                import asyncio
                import concurrent.futures
                
                fallback_path = sample_dir / f"{voice_id}.mp3"
                if voice_id in ["leminh", "giahuy", "north_male", "south_male"]:
                    edge_voice = "vi-VN-NamMinhNeural"
                else:
                    edge_voice = "vi-VN-HoaiMyNeural"
                
                async def _gen_edge_sample():
                    communicate = edge_tts.Communicate(sample_text, edge_voice)
                    await communicate.save(str(fallback_path))
                
                try:
                    loop = asyncio.get_running_loop()
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, _gen_edge_sample()).result()
                except RuntimeError:
                    asyncio.run(_gen_edge_sample())
                
                file_path = fallback_path
                logger.info(f"Đã sinh thành công giọng mẫu fallback Edge TTS cho {voice_id}.")
            except Exception as edge_err:
                logger.error(f"Lỗi khi sinh giọng mẫu fallback Edge TTS cho {voice_id}: {edge_err}")�的清晰音质。"
        
        try:
            generate_tts_audio(
                text=sample_text,
                output_path=str(file_path),
                voice=voice_code
            )
        except Exception as e:
            logger.warning(f"Lỗi khi sinh giọng mẫu {voice_id}: {e}. Tiến hành fallback sang Edge TTS.")
            try:
                import edge_tts
                import asyncio
                import concurrent.futures
                
                # Fallback path remains .mp3
                fallback_path = sample_dir / f"{voice_id}.mp3"
                if voice_id in ["leminh", "giahuy", "north_male", "south_male"]:
                    edge_voice = "vi-VN-NamMinhNeural"
                else:
                    edge_voice = "vi-VN-HoaiMyNeural"
                
                async def _gen_edge_sample():
                    communicate = edge_tts.Communicate(sample_text, edge_voice)
                    await communicate.save(str(fallback_path))
                
                try:
                    loop = asyncio.get_running_loop()
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, _gen_edge_sample()).result()
                except RuntimeError:
                    asyncio.run(_gen_edge_sample())
                
                file_path = fallback_path
                logger.info(f"Đã sinh thành công giọng mẫu fallback Edge TTS cho {voice_id}.")
            except Exception as edge_err:
                logger.error(f"Lỗi khi sinh giọng mẫu fallback Edge TTS cho {voice_id}: {edge_err}")
                    
    media_type = "audio/mpeg" if file_path.suffix == ".mp3" else "audio/wav"
    return FileResponse(str(file_path), media_type=media_type)


@router.post("/history/delete/{job_id}")
def delete_job(job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Xóa tác vụ lồng tiếng và file liên quan"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id, DubbingJob.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        
    try:
        import glob
        for file_pattern in [
            str(settings.STORAGE_DIR / "uploads" / f"{job_id}.*"),
            str(settings.STORAGE_DIR / "temp" / f"{job_id}*"),
            str(settings.STORAGE_DIR / "audio" / f"{job_id}*"),
            str(settings.STORAGE_DIR / "exports" / f"{job_id}*"),
            str(settings.STORAGE_DIR / "subtitles" / f"{job_id}*"),
        ]:
            for f in glob.glob(file_pattern):
                try:
                    os.remove(f)
                except Exception:
                    pass
    except Exception:
        pass
        
    db.delete(job)
    db.commit()
    return {"success": True, "message": "Đã xóa tác vụ thành công."}


# Khởi chạy luồng chạy ngầm tiền sinh (Pre-generation) toàn bộ các file mẫu nghe thử nếu bị thiếu
def pre_generate_all_samples():
    """Hàm chạy ngầm tuần tự sinh trước toàn bộ các file mẫu nghe thử nếu bị thiếu"""
    def _run():
        import time
        from app.config import settings
        from app.services.dubbing_engine import generate_tts_audio
        
        # Đợi 3 giây cho server uvicorn khởi động ổn định
        time.sleep(3)
        
        sample_dir = settings.STORAGE_DIR / "samples"
        os.makedirs(sample_dir, exist_ok=True)
        
        voices_map = {
            "north_female": ("vi-VN-HoaiMyNeural", "Xin chào! Tôi là giọng đọc trí tuệ nhân tạo Hoài An, mang chất âm miền Bắc trong trẻo, chuyên nghiệp và đầy tự nhiên. Tôi rất phù hợp để thuyết minh bài giảng, review phim hoặc lồng tiếng các nội dung giáo dục. Hãy cùng tôi tạo nên những video thật cuốn hút nhé!"),
            "north_male": ("vi-VN-NamMinhNeural", "Chào bạn! Tôi là Gia Huy, giọng đọc Nam miền Bắc của hệ thống Voice AI. Với tông giọng trầm ấm, rõ ràng và mạch lạc, tôi rất thích hợp cho các nội dung tin tức, phóng sự hoặc đọc tài liệu kỹ thuật. Rất hân hạnh được đồng hành cùng dự án của bạn."),
            "south_female": ("vi-VN-HoaiMyNeural", "Xin chào! Mình là Thảo Chi, giọng đọc Nữ miền Nam vô cùng ngọt ngào, dịu dàng và truyền cảm. Mình rất thích hợp để lồng tiếng cho các video tâm sự, đọc truyện đêm muộn hoặc review ẩm thực. Hãy nhấn nút bên dưới để sử dụng giọng của mình nha!"),
            "south_male": ("vi-VN-NamMinhNeural", "Chào mọi người! Mình là Minh Quân, giọng đọc Nam miền Nam đầy năng động, trẻ trung và lưu loát. Giọng của mình rất phù hợp cho các video quảng cáo sản phẩm, chia sẻ kinh nghiệm hoặc vlog đời sống. Chúc các bạn có những trải nghiệm tuyệt vời cùng Voice AI."),
            "charlie": ("charlie", "Hello there! This is a preview of Charlie, a premium AI voice from ElevenLabs. I am characterized by a warm, deep, and conversational tone, perfect for storytelling and video narration. I look forward to working with you."),
            "george": ("george", "Hello! This is George, a professional AI voice from ElevenLabs. I offer a clear, authoritative, and articulate delivery, ideal for corporate videos, presentations, and documentary narrations."),
            "callum": ("callum", "Hey there! I am Callum, an energetic and friendly AI voice from ElevenLabs. My tone is casual and engaging, which makes me a great fit for modern vlogs and social media content."),
            "will": ("will", "Hello! This is Will, a strong and confident AI voice from ElevenLabs. I deliver words with power and precision, suitable for motivational videos, sports coverage, and tutorials."),
            "charlotte": ("charlotte", "Hello! I am Charlotte, a sweet and natural AI voice from ElevenLabs. I speak with clarity and warmth, making me a great fit for conversational videos and explanations."),
            "alice": ("alice", "Hello! This is Alice, a gentle and soft AI voice from ElevenLabs. My style is peaceful and soothing, which is perfect for meditation, audiobooks, and narrative content."),
            "matilda": ("matilda", "Hi! I am Matilda, an expressive and emotional AI voice from ElevenLabs. I can bring deep narrative and storytelling elements to life in your video projects.")
        }
        
        logger.info("[Voice Sample Pre-gen] Bắt đầu kiểm tra và sinh trước các file mẫu giọng đọc...")
        for voice_id, (voice_code, sample_text) in voices_map.items():
            file_path = sample_dir / f"{voice_id}.mp3"
            
            # Xóa nếu file bị lỗi 0 bytes
            if file_path.exists() and file_path.stat().st_size == 0:
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            
            # Nếu chưa có file, sinh tuần tự
            if not file_path.exists():
                try:
                    logger.info(f"[Voice Sample Pre-gen] Đang sinh file mẫu cho: {voice_id}...")
                    generate_tts_audio(
                        text=sample_text,
                        output_path=str(file_path),
                        voice=voice_code
                    )
                    # Delay 1 giây giữa các cuộc gọi để tránh quá tải/block IP
                    time.sleep(1.0)
                except Exception as e:
                    logger.warning(f"[Voice Sample Pre-gen] Lỗi sinh mẫu cho {voice_id}: {e}. Cố gắng sinh fallback Edge TTS.")
                    try:
                        import edge_tts
                        import asyncio
                        
                        if voice_id in ["north_male", "south_male", "charlie", "george", "callum", "will"]:
                            edge_voice = "vi-VN-NamMinhNeural"
                        else:
                            edge_voice = "vi-VN-HoaiMyNeural"
                            
                        async def _gen_edge():
                            communicate = edge_tts.Communicate(sample_text, edge_voice)
                            await communicate.save(str(file_path))
                            
                        asyncio.run(_gen_edge())
                        time.sleep(1.0)
                    except Exception as edge_err:
                        logger.error(f"[Voice Sample Pre-gen] Thất bại hoàn toàn khi sinh mẫu cho {voice_id}: {edge_err}")

        logger.info("[Voice Sample Pre-gen] Hoàn thành việc chuẩn bị toàn bộ file mẫu nghe thử!")

import threading
threading.Thread(target=pre_generate_all_samples, daemon=True).start()

# Force reload to pick up newly installed dependencies like kokoro_onnx
