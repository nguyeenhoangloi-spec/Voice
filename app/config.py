import os
from pathlib import Path
from dotenv import load_dotenv

# Load environmental variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")



class Settings:
    APP_MODE: str = os.getenv("APP_MODE", "development")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "127.0.0.1")

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "supersecretkeyforjwttokenvoiceaidubbingplatform2026")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///d:/Voice_AI/storage/database.db")

    # Redis (Celery)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # AI Chế độ hoạt động
    AI_MODE: str = os.getenv("AI_MODE", "mock").lower() # mock | real
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # TTS Settings (Chỉ sử dụng Edge TTS miễn phí ổn định lâu dài)
    TTS_ENGINE: str = "edge"


    # Media
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
    MAX_VIDEO_DURATION_MINUTES: int = int(os.getenv("MAX_VIDEO_DURATION_MINUTES", "10"))

    # Storage paths
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOADS_DIR: Path = STORAGE_DIR / "uploads"
    TEMP_DIR: Path = STORAGE_DIR / "temp"
    AUDIO_DIR: Path = STORAGE_DIR / "audio"
    VIDEO_DIR: Path = STORAGE_DIR / "video"
    SUBTITLES_DIR: Path = STORAGE_DIR / "subtitles"
    EXPORTS_DIR: Path = STORAGE_DIR / "exports"

    def create_directories(self):
        """Tạo các thư mục lưu trữ nếu chưa tồn tại"""
        for directory in [
            self.UPLOADS_DIR,
            self.TEMP_DIR,
            self.AUDIO_DIR,
            self.VIDEO_DIR,
            self.SUBTITLES_DIR,
            self.EXPORTS_DIR
        ]:
            directory.mkdir(parents=True, exist_ok=True)

settings = Settings()
settings.create_directories()
