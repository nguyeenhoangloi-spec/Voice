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
from app.services.link_checker import check_url_safety, extract_clean_url
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
    url = extract_clean_url(req.url)
    
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
        "translation_mode": req.translation_mode or "natural",
        "video_context": req.video_context or "neutral",
        "video_topic": req.video_topic or "",
        "whisper_model": req.whisper_model or "base",
        "asr_method": req.asr_method or "whisper",
        "clip_start": req.clip_start or None,
        "clip_end": req.clip_end or None,
        "exact_cut": req.exact_cut if req.exact_cut is not None else True,
        "download_quality": req.download_quality or "720p",
        "cookie_content": req.cookie_content or None,
    }
    
    new_job = DubbingJob(
        id=job_id,
        user_id=user.id,
        source_url=extract_clean_url(req.source_url),
        source_type=req.source_type,
        clip_start=req.clip_start or None,
        clip_end=req.clip_end or None,
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
            "desc": "Giọng nữ đọc trong trẻo, tự nhiên, cực kỳ phù hợp thuyết minh phim, bài giảng hoặc sách nói.",
            "provider": "edge",
            "language": "vi",
            "tech_badge": "Edge Neural"
        },
        {
            "id": "namminh",
            "name": "Microsoft Edge Nam (Nam Minh - Neural)",
            "gender": "Nam",
            "region": "Việt Nam (Edge TTS)",
            "voice": "vi-VN-NamMinhNeural",
            "desc": "Giọng nam đọc trầm ấm, rõ ràng, thích hợp làm tin tức, phóng sự và tài liệu kỹ thuật.",
            "provider": "edge",
            "language": "vi",
            "tech_badge": "Edge Neural"
        },
        {
            "id": "vieneu_Trúc Ly",
            "name": "VieNeu Trúc Ly (Nữ - Bắc)",
            "gender": "Nữ",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Trúc Ly",
            "desc": "Giọng nữ miền Bắc tự nhiên, trong trẻo, lồng tiếng cực tốt và chạy hoàn toàn offline.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Phạm Tuyên",
            "name": "VieNeu Phạm Tuyên (Nam - Bắc)",
            "gender": "Nam",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Phạm Tuyên",
            "desc": "Giọng nam miền Bắc tự nhiên, rõ ràng, trầm ấm, chạy hoàn toàn offline.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Thái Sơn",
            "name": "VieNeu Thái Sơn (Nam - Nam)",
            "gender": "Nam",
            "region": "Miền Nam (VieNeu)",
            "voice": "vieneu_Thái Sơn",
            "desc": "Giọng nam miền Nam chuyên dùng kể chuyện, diễn cảm và ấm áp.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Xuân Vĩnh",
            "name": "VieNeu Xuân Vĩnh (Nam - Nam)",
            "gender": "Nam",
            "region": "Miền Nam (VieNeu)",
            "voice": "vieneu_Xuân Vĩnh",
            "desc": "Giọng nam miền Nam phong cách tự nhiên, hoạt ngôn, thích hợp làm vlog.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Thanh Bình",
            "name": "VieNeu Thanh Bình (Nam - Bắc)",
            "gender": "Nam",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Thanh Bình",
            "desc": "Giọng nam miền Bắc phong cách kể chuyện truyền cảm, lôi cuốn.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Minh Đức",
            "name": "VieNeu Minh Đức (Nam - Bắc)",
            "gender": "Nam",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Minh Đức",
            "desc": "Giọng nam miền Bắc phong cách tin tức, thời sự chuẩn mực.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Ngọc Linh",
            "name": "VieNeu Ngọc Linh (Nữ - Bắc)",
            "gender": "Nữ",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Ngọc Linh",
            "desc": "Giọng nữ miền Bắc phong cách kể chuyện nhẹ nhàng, ấm áp.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Đoan Trang",
            "name": "VieNeu Đoan Trang (Nữ - Bắc)",
            "gender": "Nữ",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Đoan Trang",
            "desc": "Giọng nữ miền Bắc tự nhiên, truyền cảm, dễ nghe.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Mai Anh",
            "name": "VieNeu Mai Anh (Nữ - Bắc)",
            "gender": "Nữ",
            "region": "Miền Bắc (VieNeu)",
            "voice": "vieneu_Mai Anh",
            "desc": "Giọng nữ miền Bắc phong cách tin tức, đọc rõ ràng, dứt khoát.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Thục Đoan",
            "name": "VieNeu Thục Đoan (Nữ - Nam)",
            "gender": "Nữ",
            "region": "Miền Nam (VieNeu)",
            "voice": "vieneu_Thục Đoan",
            "desc": "Giọng nữ miền Nam phong cách kể chuyện, ngọt ngào, truyền cảm.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Minh Triết",
            "name": "VieNeu Minh Triết (Nam - Nam)",
            "gender": "Nam",
            "region": "Miền Nam (VieNeu)",
            "voice": "vieneu_Minh Triết",
            "desc": "Giọng nam miền Nam phong cách tin tức, chuyên nghiệp.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Thùy Dung",
            "name": "VieNeu Thùy Dung (Nữ - Nam)",
            "gender": "Nữ",
            "region": "Miền Nam (VieNeu)",
            "voice": "vieneu_Thùy Dung",
            "desc": "Giọng nữ miền Nam phong cách tin tức, rõ chữ, truyền cảm.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Quang Sơn",
            "name": "VieNeu Quang Sơn (Nam - Trung)",
            "gender": "Nam",
            "region": "Miền Trung (VieNeu)",
            "voice": "vieneu_Quang Sơn",
            "desc": "Giọng nam miền Trung tự nhiên, mộc mạc và chân thực.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
        },
        {
            "id": "vieneu_Ngọc Trân",
            "name": "VieNeu Ngọc Trân (Nữ - Trung)",
            "gender": "Nữ",
            "region": "Miền Trung (VieNeu)",
            "voice": "vieneu_Ngọc Trân",
            "desc": "Giọng nữ miền Trung tự nhiên, ngọt ngào, đậm chất Huế.",
            "provider": "vieneu",
            "language": "vi",
            "tech_badge": "VieNeu Offline"
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
            "desc": v["desc"],
            "provider": "tiktok",
            "language": v.get("lang", "en"),
            "tech_badge": "CapCut Voice"
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
                "desc": f"Giọng đọc {v['gender']} chất lượng phòng thu, chạy offline hoàn toàn. Ngôn ngữ gốc: {region_name}.",
                "provider": "kokoro",
                "language": lang if lang in ["vi", "en"] else "other",
                "tech_badge": "Kokoro Studio"
            })
                 
    import os
    tiktok_session_id = os.getenv("TIKTOK_SESSION_ID", "")
    return templates.TemplateResponse(
        "user/voices.html",
        {
            "request": request,
            "user": user,
            "voices": voices,
            "tiktok_session_id": tiktok_session_id,
            "page_title": "Mẫu giọng AI lồng tiếng - VoiceAI"
        }
    )

@router.post("/voices/save-session")
def save_tiktok_session(payload: dict, user=Depends(get_current_user)):
    """API lưu trữ TikTok Session ID do người dùng dán vào từ giao diện, đồng thời xóa cache giọng cũ để ép sinh lại."""
    session_id = payload.get("session_id", "").strip()
    try:
        from app.services.tiktok_service import update_env_session_id
        update_env_session_id(session_id)
        
        # Xóa các file sample cũ của TikTok/CapCut để buộc sinh lại bằng sessionid mới
        try:
            from app.config import settings
            import glob
            sample_dir = settings.STORAGE_DIR / "samples"
            if sample_dir.exists():
                for file_path in glob.glob(str(sample_dir / "vi_vn_*.mp3")):
                    try:
                        os.remove(file_path)
                        logger.info(f"[TikTok TTS] Đã xóa file sample cũ để ép sinh lại: {file_path}")
                    except Exception as rm_err:
                        logger.error(f"[TikTok TTS] Lỗi khi xóa file {file_path}: {rm_err}")
        except Exception as cache_err:
            logger.error(f"[TikTok TTS] Lỗi khi dọn dẹp cache sample: {cache_err}")
            
        return {"success": True, "message": "Đã cập nhật Session ID và xóa cache giọng cũ thành công!"}
    except Exception as e:
        return {"success": False, "error": str(e)}



@router.get("/voices/sample/{voice_id}.mp3")
def get_voice_sample_audio(voice_id: str):
    """Sinh động (Lazy Loading) âm thanh mẫu của giọng AI và trả về dưới dạng file stream"""
    from app.config import settings
    from app.services.dubbing_engine import generate_tts_audio
    from fastapi.responses import FileResponse
    
    sample_dir = settings.STORAGE_DIR / "samples"
    os.makedirs(sample_dir, exist_ok=True)
    
    # We save as .wav for Kokoro and Vieneu, .mp3 for others
    if voice_id.startswith(("af_", "am_", "bf_", "bm_", "ef_", "em_", "ff_", "hf_", "hm_", "if_", "im_", "pf_", "pm_", "jf_", "jm_", "zf_", "vieneu_")):
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
            sample_text = "Bonjour! Je suis une voix de synthèse vocale de haute qualité de Kokoro AI, qui s'exécute complètement hors ligne với một sự rõ ràng như ở phòng thu."
        elif voice_id.startswith("vieneu_"):
            clean_name = voice_id.replace("vieneu_", "")
            sample_text = f"Xin chào! Đây là bản nghe thử giọng đọc tiếng Việt cực kỳ chất lượng và truyền cảm {clean_name}, được sinh hoàn toàn offline bằng mô hình trí tuệ nhân tạo của dự án VieNeu TTS."
            voice_code = voice_id
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


@router.post("/job/{job_id}/translate-segment")
async def api_translate_segment(
    job_id: str,
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Dịch một đoạn thoại bằng AI (Gemini → fallback Google Translate).
    Payload: { text: str, context?: str }
    Response: { translation: str, engine: str }
    """
    text: str = (payload.get("text") or "").strip()
    context: str = (payload.get("context") or "neutral").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Thiếu trường 'text' để dịch.")

    # ── Cache lookup ──────────────────────────────────────────────────────
    import hashlib, json as _json
    cache_dir = settings.STORAGE_DIR / "translate_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.md5(f"{text}|vi|{context}".encode()).hexdigest()
    cache_file = cache_dir / f"{cache_key}.json"

    if cache_file.exists():
        try:
            cached = _json.loads(cache_file.read_text(encoding="utf-8"))
            return {"translation": cached["translation"], "engine": "cache"}
        except Exception:
            pass  # Corrupted cache, re-translate

    # ── Translate using AI ────────────────────────────────────────────────
    translation: str = ""
    engine_used: str = "google"

    # --- Attempt 1: Gemini API ---
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            import httpx as _httpx
            prompt = (
                f"Bạn là chuyên gia lồng tiếng phim ảnh Việt Nam với 20 năm kinh nghiệm.\n"
                f"Ngữ cảnh video: {context}\n\n"
                f"Dịch câu sau sang tiếng Việt tự nhiên, phù hợp để lồng tiếng (dubbing).\n"
                f"Giữ nguyên ý nghĩa, độ ngắn và nhịp điệu của câu gốc.\n"
                f"CHỈ trả về bản dịch tiếng Việt, KHÔNG giải thích, KHÔNG thêm ngoặc kép.\n\n"
                f"Câu gốc: {text}"
            )
            async with _httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    headers={"Content-Type": "application/json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    translation = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                        .strip()
                    )
                    if translation:
                        engine_used = "gemini"
        except Exception as e:
            logger.warning(f"[Translate] Gemini API failed: {e}")

    # --- Attempt 2: Google Translate fallback ---
    if not translation:
        try:
            from concurrent.futures import ThreadPoolExecutor
            def _google_translate():
                from deep_translator import GoogleTranslator
                return GoogleTranslator(source="auto", target="vi").translate(text)
            with ThreadPoolExecutor(max_workers=1) as pool:
                translation = await asyncio.get_event_loop().run_in_executor(pool, _google_translate)
            engine_used = "google"
        except Exception as e:
            logger.error(f"[Translate] Google Translate failed: {e}")
            raise HTTPException(status_code=500, detail=f"Không thể dịch câu này: {e}")

    # ── Write cache ───────────────────────────────────────────────────────
    try:
        cache_file.write_text(
            _json.dumps({"translation": translation, "engine": engine_used}, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass

    return {"translation": translation, "engine": engine_used}


@router.post("/job/{job_id}/preview-tts")
async def api_preview_segment_tts(
    job_id: str,
    payload: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    API sinh nhanh âm thanh nghe thử (Preview TTS) cho một phân đoạn thoại.
    Được gọi từ Timeline Editor khi người dùng bấm nút 'Nghe thử'.

    Request body:
        - translation (str): Bản dịch tiếng Việt cần chuyển thành giọng nói
        - voice (str, optional): Mã giọng đọc (default: vi-VN-HoaiMyNeural)
        - rate (str, optional): Tốc độ đọc, ví dụ '+0%', '+15%' (default: '+0%')
        - segment_id (int, optional): ID phân đoạn để định danh file cache
    """
    from fastapi.responses import FileResponse

    # Validate request
    translation = payload.get("translation", "").strip()
    if not translation:
        raise HTTPException(status_code=400, detail="Nội dung bản dịch không được trống.")

    voice = payload.get("voice", "vi-VN-HoaiMyNeural")
    rate = payload.get("rate", "+0%")
    segment_id = payload.get("segment_id", "temp")

    # Verify job belongs to user (security check)
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
    if job.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập tác vụ này.")

    # Create preview audio in storage/previews/
    preview_dir = settings.STORAGE_DIR / "previews"
    os.makedirs(preview_dir, exist_ok=True)

    # Unique filename per job+segment for caching (can re-use if same text)
    import hashlib
    cache_key = hashlib.md5(f"{voice}:{rate}:{translation}".encode()).hexdigest()[:12]
    preview_path = str(preview_dir / f"{job_id}_prev_{segment_id}_{cache_key}.mp3")

    # Check cache: if audio already generated, return immediately
    if os.path.exists(preview_path) and os.path.getsize(preview_path) > 100:
        return FileResponse(
            preview_path,
            media_type="audio/mpeg",
            headers={"Cache-Control": "public, max-age=300"}
        )

    # Generate TTS audio (run in thread pool to avoid blocking event loop)
    import asyncio
    import concurrent.futures
    from app.services.dubbing_engine import generate_tts_audio, preprocess_text_for_tts

    try:
        cleaned_text = preprocess_text_for_tts(translation)
        if cleaned_text and cleaned_text[-1] not in '.!?,;:…':
            cleaned_text += '.'

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool,
                lambda: generate_tts_audio(
                    text=cleaned_text,
                    output_path=preview_path,
                    voice=voice,
                    rate=rate
                )
            )
    except Exception as e:
        logger.error(f"Preview TTS failed for job {job_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi sinh giọng nói thử: {str(e)}"
        )

    if not os.path.exists(preview_path) or os.path.getsize(preview_path) < 100:
        raise HTTPException(status_code=500, detail="File âm thanh preview bị rỗng hoặc không tồn tại.")

    return FileResponse(
        preview_path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=300"}
    )


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

    _run()

import threading
threading.Thread(target=pre_generate_all_samples, daemon=True).start()

# Force reload to pick up newly installed dependencies like kokoro_onnx
