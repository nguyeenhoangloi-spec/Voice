from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import templates, get_current_user
from app.models.job import DubbingJob

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def user_dashboard(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Render trang Dashboard của người dùng"""
    # Lấy các tác vụ lồng tiếng của người dùng hiện tại, sắp xếp theo thời gian tạo mới nhất
    jobs = db.query(DubbingJob).filter(DubbingJob.user_id == user.id).order_by(DubbingJob.created_at.desc()).all()
    
    # Tính toán số liệu thống kê cơ bản
    total_jobs = len(jobs)
    completed_jobs = sum(1 for j in jobs if j.status == "completed")
    processing_jobs = sum(1 for j in jobs if j.status in ["processing", "pending"])
    failed_jobs = sum(1 for j in jobs if j.status == "failed")
    
    return templates.TemplateResponse(
        "user/dashboard.html",
        {
            "request": request,
            "user": user,
            "jobs": jobs,
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "processing_jobs": processing_jobs,
            "failed_jobs": failed_jobs,
            "page_title": "Bảng điều khiển - VoiceAI"
        }
    )
