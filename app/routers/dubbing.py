import os
import uuid
import shutil
import json
import asyncio
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
    # Kiểm tra dung lượng
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    
    # Đọc thử header để lấy dung lượng nếu có
    # Cách tốt nhất là chép file tạm và kiểm tra kích thước
    file_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    # Chỉ nhận định dạng hợp lệ
    if file_ext not in [".mp4", ".webm", ".mp3", ".wav", ".ogg", ".aac", ".m4a"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Định dạng tệp tin không được hỗ trợ."
        )
        
    temp_path = settings.UPLOADS_DIR / f"{file_id}{file_ext}"
    
    try:
        # Lưu file tạm xuống đĩa
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_size = os.path.getsize(temp_path)
        if file_size > max_bytes:
            # Xóa file nếu vượt quá giới hạn
            os.remove(temp_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Kích thước tệp tin vượt quá giới hạn {settings.MAX_UPLOAD_SIZE_MB} MB."
            )
            
        # Probe file thông qua ffprobe
        probe_meta = probe_media_file(str(temp_path))
        
        # Kiểm tra thời lượng
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
    
    # 1. Tạo bản ghi DubbingJob trong DB
    voice_config = {
        "voice_gender": req.voice_gender,
        "voice_region": req.voice_region,
        "voice_emotion": req.voice_emotion,
        "keep_bg_music": req.keep_bg_music,
        "generate_subtitles": req.generate_subtitles,
        "translation_mode": req.translation_mode
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
    
    # 2. Khởi tạo sẵn 20 bản ghi JobStep tương ứng
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

    # Import run task ngầm
    from app.workers.dubbing_tasks import run_dubbing_pipeline
    
    # 3. Kích hoạt xử lý chạy ngầm
    # Nếu cài đặt Celery & Redis thì dispatch qua Celery, ở đây ta dùng FastAPI BackgroundTasks để nhẹ và độc lập
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
        # Nếu là admin thì vẫn cho phép xem
        if user.role == "admin":
            job = db.query(DubbingJob).filter(DubbingJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
            
    # Lấy thông tin 20 steps
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
        
    # Nạp thêm thông tin segments nếu có (để render editor khi hoàn tất)
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

    # Lấy files exports nếu đã có
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
                    
                # Gửi thông tin rút gọn về giao diện
                status_data = {
                    "status": job.status,
                    "progress_percent": job.progress_percent,
                    "current_step": job.current_step,
                    "current_step_name": job.current_step_name,
                    "error_message": job.error_message
                }
                yield f"data: {json.dumps(status_data)}\n\n"
                
                # Kết thúc stream nếu job đã xong hoặc thất bại
                if job.status in ["completed", "failed"]:
                    break
            finally:
                db.close()
            await asyncio.sleep(1.0) # Đợi 1 giây trước khi check tiếp
            
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
            
    # Cập nhật các segments trong DB
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
            
    # Reset job và các steps từ bước 15 (Đồng bộ giọng nói) trở đi để kết xuất lại
    job.status = "pending"
    job.progress_percent = 70
    job.current_step = 15
    job.current_step_name = PIPELINE_STEPS[14]
    job.completed_at = None
    
    steps = db.query(JobStep).filter(JobStep.job_id == job_id).all()
    for s in steps:
        if s.step_number >= 15:
            s.status = "pending"
            s.started_at = None
            s.completed_at = None
            s.log_message = "Chờ kết xuất lại sau khi lưu chỉnh sửa."
            
    db.commit()
    
    # Chạy lại pipeline ngầm từ bước 15
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
    """Render danh sách mẫu giọng AI hệ thống"""
    # Tạo các file âm thanh mẫu nếu chưa tồn tại
    sample_dir = settings.STORAGE_DIR / "samples"
    os.makedirs(sample_dir, exist_ok=True)
    
    voices = [
        {
            "id": "north_male",
            "name": "Nam miền Bắc (Gia Huy)",
            "gender": "Nam",
            "region": "Miền Bắc",
            "voice": "vi-VN-NamMinhNeural",
            "text": "Xin chào! Đây là bản nghe thử giọng đọc trí tuệ nhân tạo Nam miền Bắc Gia Huy của hệ thống Voice AI. Rất hân hạnh được phục vụ bạn.",
            "desc": "Giọng đọc trầm ấm, truyền cảm, thích hợp làm tin tức, tài liệu."
        },
        {
            "id": "north_female",
            "name": "Nữ miền Bắc (Hoài An)",
            "gender": "Nữ",
            "region": "Miền Bắc",
            "voice": "vi-VN-HoaiMyNeural",
            "text": "Xin chào! Đây là bản nghe thử giọng đọc trí tuệ nhân tạo Nữ miền Bắc Hoài An của hệ thống Voice AI. Rất hân hạnh được phục vụ bạn.",
            "desc": "Giọng đọc trong trẻo, chuyên nghiệp, phù hợp với bài giảng, review phim."
        },
        {
            "id": "south_male",
            "name": "Nam miền Nam (Minh Quân)",
            "gender": "Nam",
            "region": "Miền Nam",
            "voice": "vi-VN-NamMinhNeural",
            "text": "Xin chào! Đây là bản nghe thử giọng đọc trí tuệ nhân tạo Nam miền Nam Minh Quân của hệ thống Voice AI. Rất hân hạnh được phục vụ bạn.",
            "desc": "Giọng đọc lưu loát, năng động, thích hợp quảng cáo, chia sẻ kinh nghiệm."
        },
        {
            "id": "south_female",
            "name": "Nữ miền Nam (Thảo Chi)",
            "gender": "Nữ",
            "region": "Miền Nam",
            "voice": "vi-VN-HoaiMyNeural",
            "text": "Xin chào! Đây là bản nghe thử giọng đọc trí tuệ nhân tạo Nữ miền Nam Thảo Chi của hệ thống Voice AI. Rất hân hạnh được phục vụ bạn.",
            "desc": "Giọng nói ngọt ngào, dịu dàng, phù hợp truyện đọc, tâm sự."
        }
    ]
    
    import edge_tts
    import asyncio
    import concurrent.futures

    async def _gen_voice_sample(text: str, voice: str, path: str):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(path)

    for v in voices:
        file_path = sample_dir / f"{v['id']}.wav"
        if not file_path.exists():
            try:
                # Chạy hàm async trong sync route
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, _gen_voice_sample(v["text"], v["voice"], str(file_path))).result()
                else:
                    loop.run_until_complete(_gen_voice_sample(v["text"], v["voice"], str(file_path)))
            except Exception as e:
                logger.error(f"Lỗi khi sinh giọng mẫu {v['id']}: {e}")
                # Fallback file im lặng nếu lỗi
                import wave
                import struct
                try:
                    with wave.open(str(file_path), "wb") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(44100)
                        for _ in range(44100):
                            w.writeframes(struct.pack('h', 0))
                except Exception:
                    pass
                
    return templates.TemplateResponse(
        "user/voices.html",
        {
            "request": request,
            "user": user,
            "voices": voices,
            "page_title": "Mẫu giọng AI lồng tiếng - VoiceAI"
        }
    )


@router.post("/history/delete/{job_id}")
def delete_job(job_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Xóa tác vụ lồng tiếng và file liên quan"""
    job = db.query(DubbingJob).filter(DubbingJob.id == job_id, DubbingJob.user_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        
    # Xóa các files vật lý nếu tồn tại
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
        
    # Xóa khỏi DB
    db.delete(job)
    db.commit()
    return {"success": True, "message": "Đã xóa tác vụ thành công."}


