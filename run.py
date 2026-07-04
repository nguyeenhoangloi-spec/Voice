import uvicorn
from app.config import settings
from app.utils.ffmpeg_utils import inject_ffmpeg_to_path

if __name__ == "__main__":
    # Clean PATH and inject working FFmpeg binaries on startup
    inject_ffmpeg_to_path()
    
    print(f"Starting VoiceAI server on {settings.HOST}:{settings.PORT} (AI_MODE={settings.AI_MODE})...")
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.APP_MODE == "development"
    )
