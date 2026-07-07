import uvicorn
from app.config import settings
from app.utils.ffmpeg_utils import inject_ffmpeg_to_path

if __name__ == "__main__":
    # Clean PATH and inject working FFmpeg binaries on startup
    inject_ffmpeg_to_path()
    
    # In ra dòng link cụ thể click được
    host_display = "127.0.0.1" if settings.HOST == "0.0.0.0" else settings.HOST
    print("\n" + "="*50)
    print(f"VOICE AI DUBBING SERVER IS READY!")
    print(f"CLICK TO OPEN: http://{host_display}:{settings.PORT}")
    print("="*50 + "\n")
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.APP_MODE == "development"
    )
# Reload trigger: 2026-07-07 21:39
