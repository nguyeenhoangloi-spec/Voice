from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import templates, get_current_user_optional

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def home_page(request: Request, user=Depends(get_current_user_optional)):
    """Render trang chủ giới thiệu dịch vụ lồng tiếng VoiceAI"""
    return templates.TemplateResponse(
        "public/home.html", 
        {"request": request, "user": user, "page_title": "VoiceAI - AI Video Dubbing Platform"}
    )

@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request, user=Depends(get_current_user_optional)):
    """Render trang bảng giá gói dịch vụ"""
    return templates.TemplateResponse(
        "public/pricing.html", 
        {"request": request, "user": user, "page_title": "Gói dịch vụ - VoiceAI"}
    )

@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request, user=Depends(get_current_user_optional)):
    """Render trang hướng dẫn sử dụng & câu hỏi thường gặp"""
    return templates.TemplateResponse(
        "public/help.html", 
        {"request": request, "user": user, "page_title": "Hướng dẫn sử dụng - VoiceAI"}
    )

@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request, user=Depends(get_current_user_optional)):
    """Render trang điều khoản sử dụng và chính sách quyền riêng tư"""
    return templates.TemplateResponse(
        "public/terms.html", 
        {"request": request, "user": user, "page_title": "Điều khoản & Quyền riêng tư - VoiceAI"}
    )
