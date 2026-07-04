from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
import jwt
from sqlalchemy.orm import Session
from datetime import datetime
import os

from app.config import settings
from app.database import get_db
from app.models.user import User

# Khởi tạo Jinja2 templates
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["settings"] = settings

# Cấu hình OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Lấy thông tin người dùng từ JWT Token nằm trong Cookie hoặc Authorization Header.
    """
    token = request.cookies.get("access_token")
    
    # Fallback kiểm tra Authorization header nếu không có cookie
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
        
    # Loại bỏ tiền tố 'Bearer ' trong cookie nếu có
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "")
        
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims"
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )
        
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """
    Lấy thông tin người dùng nếu đã đăng nhập, trả về None nếu chưa đăng nhập thay vì lỗi 401.
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None

def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Đảm bảo người dùng hiện tại có quyền Admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user
