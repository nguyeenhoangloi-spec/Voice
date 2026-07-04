from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import templates, get_current_admin
from app.models.job import DubbingJob
from app.models.user import User

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def admin_root(request: Request, admin=Depends(get_current_admin)):
    """Chuyển hướng trang chính admin về trang tổng quan"""
    return RedirectResponse(url="/admin/overview", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/overview", response_class=HTMLResponse)
def admin_overview(request: Request, admin=Depends(get_current_admin), db: Session = Depends(get_db)):
    """Hiển thị tổng quan hệ thống và các job của tất cả người dùng"""
    jobs = db.query(DubbingJob).order_by(DubbingJob.created_at.desc()).all()
    users = db.query(User).all()
    
    total_jobs = len(jobs)
    completed_jobs = sum(1 for j in jobs if j.status == "completed")
    processing_jobs = sum(1 for j in jobs if j.status in ["processing", "pending"])
    failed_jobs = sum(1 for j in jobs if j.status == "failed")
    
    return templates.TemplateResponse(
        "admin/overview.html",
        {
            "request": request,
            "user": admin,
            "jobs": jobs,
            "users": users,
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "processing_jobs": processing_jobs,
            "failed_jobs": failed_jobs,
            "page_title": "Quản trị hệ thống - VoiceAI"
        }
    )
