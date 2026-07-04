import os

log_file = "d:/Voice_AI/server.log"
if os.path.exists(log_file):
    try:
        # Try reading as UTF-16
        with open(log_file, "r", encoding="utf-16") as f:
            content = f.read()
    except Exception:
        # Fallback to UTF-8
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
    print(content[-2000:])  # Print last 2000 characters
else:
    print("Log file not found.")
