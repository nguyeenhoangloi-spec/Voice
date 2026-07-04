from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.database import get_db
from app.dependencies import templates, get_current_user_optional
from app.models.user import User, EmailOTP
from app.utils.security import hash_password, verify_password, create_access_token

router = APIRouter()

@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, user=Depends(get_current_user_optional)):
    """Hiển thị trang đăng ký tài khoản"""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("auth/register.html", {"request": request, "error": None})

@router.post("/register")
def register_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(None),
    db: Session = Depends(get_db)
):
    """Xử lý đăng ký tài khoản mới"""
    # Kiểm tra email tồn tại
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return templates.TemplateResponse(
            "auth/register.html", 
            {"request": request, "error": "Email này đã được sử dụng."}
        )
    
    # Mã hóa mật khẩu và lưu người dùng mới
    hashed = hash_password(password)
    # Tự động gán quyền admin cho tài khoản đầu tiên để kiểm thử dễ dàng hơn
    user_count = db.query(User).count()
    role = "admin" if user_count == 0 else "user"
    
    new_user = User(
        email=email,
        hashed_password=hashed,
        full_name=full_name,
        role=role,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    
    # Chuyển hướng sang trang đăng nhập với thông báo thành công
    response = RedirectResponse(url="/auth/login?registered=true", status_code=status.HTTP_303_SEE_OTHER)
    return response

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, registered: bool = False, user=Depends(get_current_user_optional)):
    """Hiển thị trang đăng nhập"""
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    success_msg = "Đăng ký thành công! Vui lòng đăng nhập." if registered else None
    return templates.TemplateResponse(
        "auth/login.html", 
        {"request": request, "error": None, "success": success_msg}
    )

@router.post("/login")
def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Xử lý đăng nhập, cấp JWT token qua Cookie"""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "auth/login.html", 
            {"request": request, "error": "Email hoặc mật khẩu không chính xác.", "success": None}
        )
    
    if not user.is_active:
        return templates.TemplateResponse(
            "auth/login.html", 
            {"request": request, "error": "Tài khoản của bạn đã bị khóa.", "success": None}
        )
    
    # Tạo JWT token
    access_token = create_access_token(data={"sub": user.email})
    
    # Thiết lập cookie JWT
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=1440 * 60, # 24 giờ
        expires=1440 * 60,
        samesite="lax",
        secure=False # Chạy Local thì False, Production HTTPS thì True
    )
    return response

@router.get("/logout")
def logout():
    """Đăng xuất, xóa Cookie JWT"""
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie("access_token")
    return response
