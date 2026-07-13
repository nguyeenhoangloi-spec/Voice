import os
import sys

# Khắc phục lỗi DLL load failed (WinError 127) và lỗi crash duplicate MKL trên Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Lọc sạch PATH để loại bỏ CUDA Toolkit hệ thống (tránh xung đột phiên bản CUDA DLL)
path_list = os.environ.get("PATH", "").split(os.pathsep)
cleaned_paths = []
for p in path_list:
    if not p:
        continue
    p_lower = p.lower()
    if "nvidia gpu computing toolkit" in p_lower or "cuda" in p_lower:
        if "envs\\voiceai" not in p_lower and "envs/voiceai" not in p_lower:
            continue
    cleaned_paths.append(p)

python_dir = os.path.dirname(sys.executable)
library_bin = os.path.join(python_dir, "Library", "bin")
if os.name == 'nt' and os.path.exists(library_bin):
    cleaned_paths.insert(0, library_bin)
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(library_bin)
        except Exception:
            pass

os.environ["PATH"] = os.pathsep.join(cleaned_paths)

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
