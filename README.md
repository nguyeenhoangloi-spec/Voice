# VoiceAI - Hệ thống Lồng tiếng Video tự động bằng AI

Hệ thống lồng tiếng video hoặc nội dung từ liên kết sang tiếng Việt bằng AI, hoạt động tốt trên desktop, tablet và mobile.

---

## Hướng dẫn cài đặt và vận hành

### 1. Cài đặt các công cụ hệ thống

#### Cài đặt Miniconda:
- Tải và cài đặt Miniconda từ trang chủ: [Miniconda Downloads](https://docs.anaconda.com/miniconda/)
- Đảm bảo `conda` đã được thêm vào biến môi trường hệ thống.

#### Cài đặt FFmpeg:
- Tải FFmpeg build cho hệ điều hành của bạn: [FFmpeg Downloads](https://ffmpeg.org/download.html)
- Trên Windows, thêm đường dẫn thư mục `bin` của FFmpeg vào biến môi trường `PATH`.
- Xác minh bằng cách chạy lệnh `ffmpeg -version` và `ffprobe -version` trong terminal.

---

### 2. Thiết lập môi trường Python

Mở terminal tại thư mục gốc dự án và chạy các lệnh:

```bash
# Tạo môi trường ảo conda tên là voiceai với python 3.11
conda create -n voiceai python=3.11 -y

# Kích hoạt môi trường
conda activate voiceai

# Cài đặt các thư viện Python
pip install -r requirements.txt
```

---

### 3. Cấu hình file `.env`

- Sao chép file cấu hình mẫu:
  ```bash
  cp .env.example .env
  ```
- Mở file `.env` vừa tạo và điền các tham số cấu hình:
  - `APP_MODE`: Chế độ chạy (mặc định: `development`).
  - `AI_MODE`: Đặt là `mock` để chạy giả lập không cần các API key và GPU, hoặc đặt là `real` để chạy mô hình thực tế.
  - Điền các khóa API như `OPENAI_API_KEY`, `GEMINI_API_KEY` nếu bạn muốn chạy thực tế.

---

### 4. Khởi tạo cơ sở dữ liệu và thư mục lưu trữ

Hệ thống lưu trữ cơ sở dữ liệu SQLite trong thư mục `storage`. Hãy chạy lệnh sau để khởi tạo:

```bash
# Khởi tạo thư mục chứa cơ sở dữ liệu và file tạm
mkdir storage/uploads storage/temp storage/audio storage/video storage/subtitles storage/exports -p

# Khởi tạo migrations database qua Alembic
alembic upgrade head
```

---

### 5. Chạy các dịch vụ ngầm

Nếu bạn sử dụng Celery + Redis cho hàng đợi tác vụ lồng tiếng:
- Đảm bảo máy tính đã cài đặt và đang chạy Redis server ở cổng mặc định `6379`.
- Kích hoạt Celery worker trong môi trường `voiceai`:
  ```bash
  celery -A app.workers.celery_app worker --loglevel=info
  ```

---

### 6. Khởi động Web Server

Để chạy ứng dụng web FastAPI, sử dụng lệnh:

```bash
python run.py
```
Hoặc:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

### 7. Truy cập website trong cùng mạng LAN

- Trên máy chủ chạy ứng dụng: Truy cập [http://localhost:8000](http://localhost:8000).
- Trên các thiết bị khác trong cùng mạng LAN (máy tính khác, điện thoại di động):
  - Tìm địa chỉ IP nội bộ của máy chủ (chạy lệnh `ipconfig` trên Windows hoặc `ifconfig`/`ip a` trên Linux/macOS). Ví dụ: `192.168.1.15`.
  - Trên điện thoại/máy tính bảng, mở trình duyệt và truy cập: `http://192.168.1.15:8000`.
