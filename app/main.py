import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.database import Base, engine
from app.routers import public, auth, dashboard, dubbing, admin

# Khởi tạo các bảng cơ sở dữ liệu nếu chưa dùng Alembic
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="VoiceAI - AI Video Dubbing Platform",
    description="Hệ thống lồng tiếng video hoặc nội dung từ liên kết sang tiếng Việt bằng AI",
    version="1.0.0"
)

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Có thể giới hạn cấu hình theo nhu cầu thực tế
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tạo các thư mục lưu trữ nếu chưa có
settings.create_directories()

# Tạo thư mục static nếu chưa tồn tại
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "css"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "js"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "images"), exist_ok=True)

# Mount thư mục static phục vụ các file CSS, JS, hình ảnh
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Mount thư mục storage phục vụ các file xuất kết quả (video/audio/subtitles)
app.mount("/storage", StaticFiles(directory=str(settings.STORAGE_DIR)), name="storage")

# Đăng ký các routers của ứng dụng
app.include_router(public.router)
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(dubbing.router, prefix="/dubbing", tags=["Dubbing Pipeline"])
app.include_router(admin.router, prefix="/admin", tags=["Admin Portal"])

@app.get("/health")
def health_check():
    """Endpoint kiểm tra trạng thái hoạt động của server"""
    return {
        "status": "healthy",
        "app_mode": settings.APP_MODE,
        "ai_mode": settings.AI_MODE
    }
