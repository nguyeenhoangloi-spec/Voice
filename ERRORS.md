# Error Tracking & Learning Log (ERRORS.md)

Dưới đây là ghi nhận lịch sử các lỗi phát sinh trong quá trình xây dựng dự án và giải pháp khắc phục nhằm tránh lặp lại lỗi tương tự.

---

## [2026-07-04 20:03] - ModuleNotFoundError: No module named 'jose'

- **Type**: Integration
- **Severity**: High
- **File**: `app/dependencies.py:4`
- **Agent**: Voice
- **Root Cause**: Module `python-jose` được gọi import trong code nhưng trong `requirements.txt` chỉ cài đặt thư viện `pyjwt`.
- **Error Message**: 
  ```text
  tests\conftest.py:6: in <module>
      from app.main import app
  ...
  app\dependencies.py:4: in <module>
      from jose import JWTError, jwt
  E   ModuleNotFoundError: No module named 'jose'
  ```
- **Fix Applied**: Thay thế import và logic decode từ `jose` sang thư viện `pyjwt` (`import jwt` và bắt ngoại lệ `jwt.PyJWTError`).
- **Prevention**: Kiểm tra chéo cấu hình `requirements.txt` với các câu lệnh import thực tế trong file trước khi viết code.
- **Status**: Fixed

---

## [2026-07-04 20:04] - OperationalError: no such table: users (SQLite In-Memory isolation)

- **Type**: Integration
- **Severity**: High
- **File**: `tests/conftest.py:20`
- **Agent**: Voice
- **Root Cause**: Khi chạy SQLite `:memory:`, mỗi connection/session đại diện cho một cơ sở dữ liệu riêng biệt hoàn toàn. Do đó, session được Client gọi không nhìn thấy các bảng đã được sinh ra trên kết nối chính. Ngoài ra, việc thiếu `import app.models` khiến các bảng không được nạp vào metadata của Base trước khi gọi `create_all`.
- **Error Message**: 
  ```text
  E       sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: users
  E       [SQL: SELECT users.id AS users_id ... FROM users]
  ```
- **Fix Applied**: 
  1. Thêm lệnh `import app.models` trong `conftest.py` để khai báo các tables trên metadata của Base.
  2. Sử dụng cấu hình `poolclass=StaticPool` trong `create_engine` để ép SQLite in-memory dùng chung một kết nối duy nhất.
- **Prevention**: Khi viết test fixture cho SQLite in-memory, luôn import model package và sử dụng StaticPool để chia sẻ connection.
- **Status**: Fixed

---

## [2026-07-04 20:33] - Video corrupt placeholder on missing system FFmpeg

- **Type**: Runtime
- **Severity**: High
- **File**: `app/workers/dubbing_tasks.py:186`
- **Agent**: Voice
- **Root Cause**: Khi hệ thống thiếu `ffmpeg` trong PATH, mock pipeline bắt lỗi ngoại lệ và ghi một chuỗi text `"Mock Video data"` vào tệp `.mp4`, dẫn đến việc trình duyệt không thể phát được video và báo lỗi 0:00.
- **Fix Applied**: Xây dựng module `app/utils/media.py` tải một tệp video `.mp4` mẫu siêu nhẹ (28KB) từ W3C WPT test và lưu đè lên file kết quả, giúp trình phát video của trình duyệt phát lại bình thường.
- **Prevention**: Tránh ghi dữ liệu text thô vào các tệp tin đa phương tiện khi thiết lập phương án dự phòng (fallback).
- **Status**: Fixed

---

## [2026-07-04 20:34] - Dead links for History & Voice Samples in Sidebar

- **Type**: Logic
- **Severity**: Medium
- **File**: `app/templates/components/sidebar.html:21-28`
- **Agent**: Voice
- **Root Cause**: Các thẻ điều hướng Lịch sử và Mẫu giọng liên kết sai địa chỉ (`/dashboard` và `#`) và chưa có các trang giao diện phục vụ.
- **Fix Applied**: 
  1. Tạo router và template hiển thị lịch sử tác vụ `/dubbing/history`.
  2. Tạo router và template nghe thử giọng đọc mẫu `/dubbing/voices` kèm theo các file âm thanh mẫu `.wav` giả lập cực nhẹ.
  3. Cập nhật liên kết chính xác trong sidebar.
- **Prevention**: Luôn tạo đầy đủ các trang giao diện đã liệt kê trên thanh menu điều hướng chính.
- **Status**: Fixed

---

## [2026-07-05 11:35] - NameError: name 'time' is not defined in generate_fpt_tts

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:184`
- **Agent**: Voice
- **Root Cause**: Hàm `generate_fpt_tts` sử dụng `time.sleep(2)` để thăm dò (poll) kết quả file âm thanh trả về từ FPT.AI TTS API V5, tuy nhiên module `time` chưa được import ở đầu tệp `app/services/dubbing_engine.py`.
- **Error Message**: 
  ```text
  TTS generation failed for segment 37: name 'time' is not defined
  Fallback TTS also failed for segment 37: name 'time' is not defined
  ```
- **Fix Applied**: Thêm câu lệnh `import time` vào phần đầu tệp `app/services/dubbing_engine.py`.
- **Prevention**: Thực hiện kiểm tra chất lượng tĩnh (linter) hoặc chạy test suite với engine thực tế để sớm phát hiện các biến/module chưa định nghĩa.
- **Status**: Fixed

---

## [2026-07-06 22:30] - Giao diện Tác vụ gần đây không đổi View (List/Grid) nếu không tải lại trang

- **Type**: Logic
- **Severity**: Medium
- **File**: `app/templates/user/dashboard.html:487`
- **Agent**: Voice
- **Root Cause**: CSS có các rule `.view-mode-grid` và `.view-mode-list` sử dụng `!important` nhắm vào `#container-list-view` và `#container-grid-view`. JavaScript chỉ thay đổi thuộc tính `style.display` của hai container này nhưng không cập nhật class view-mode trên phần tử cha `#dashboard-recent-section`, dẫn đến việc các thuộc tính CSS `!important` ghi đè hoàn toàn hiển thị của JS cho tới khi F5 reload (chạy inline script cập nhật class cha).
- **Fix Applied**: Cập nhật hàm `setViewMode(mode)` trong file JavaScript để xoá và thêm các class `view-mode-list`/`view-mode-grid` trên phần tử cha `#dashboard-recent-section` tương ứng với chế độ xem được chọn.
- **Prevention**: Khi kết hợp JS toggle và CSS có độ ưu tiên cao (`!important`), luôn cập nhật các class trạng thái trên phần tử cha/bọc thay vì chỉ gán kiểu inline.
- **Status**: Fixed

---

## [2026-07-06 22:45] - Pipeline step 4 failed: yt-dlp error "Requested format is not available" due to missing FFmpeg

- **Type**: Runtime
- **Severity**: High
- **File**: `app/services/link_adapters/youtube.py:154`
- **Agent**: Voice
- **Root Cause**: Thư viện `yt-dlp` khi tải video từ YouTube yêu cầu công cụ `ffmpeg` để gộp dòng video và âm thanh chất lượng tốt nhất (`bestvideo+bestaudio`). Do môi trường ảo Python thiếu package `imageio-ffmpeg` (cung cấp binary FFmpeg tích hợp), `yt-dlp` báo lỗi không có format khả dụng.
- **Error Message**: 
  ```text
  Pipeline step 4 failed: All download strategies failed. Last error: ERROR: [youtube] jt4C4cQ7BeI: Requested format is not available. Use --list-formats for a list of available formats
  ```
- **Fix Applied**: Cài đặt gói `imageio-ffmpeg` và nâng cấp `yt-dlp` lên phiên bản mới nhất (`2026.7.4`) để tự động tích hợp FFmpeg vào session PATH thông qua `app/utils/ffmpeg_utils.py`, đồng thời cập nhật file `requirements.txt`.
- **Prevention**: Đảm bảo các thư viện nhị phân bên ngoài (như FFmpeg) luôn được khai báo và cài đặt tự động qua các package tương thích (như `imageio-ffmpeg`) trong `requirements.txt`.
- **Status**: Fixed

---

## [2026-07-06 22:58] - Pipeline step 8 failed: No module named 'whisper'

- **Type**: Integration
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:43`
- **Agent**: Voice
- **Root Cause**: Pipeline lồng tiếng sử dụng OpenAI Whisper ở bước thứ 8 để nhận diện giọng nói (ASR). Do môi trường ảo Python thiếu thư viện `openai-whisper` (chưa được khai báo trong `requirements.txt`), FastAPI ném ra lỗi `ModuleNotFoundError: No module named 'whisper'`.
- **Error Message**: 
  ```text
  Pipeline step 8 failed: No module named 'whisper'
  Pipeline failed for Job 3e6dc980-ab74-4443-86f8-393752bd47ea: No module named 'whisper'
  ```
- **Prevention**: Rà soát kỹ các thư viện import động hoặc local import trong code backend để khai báo đầy đủ trong `requirements.txt`.
- **Status**: Fixed

---

## [2026-07-06 23:03] - Pipeline step 8 failed: [WinError 2] The system cannot find the file specified (Whisper transcribing)

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:38`
- **Agent**: Voice
- **Root Cause**: Thư viện `openai-whisper` khi thực hiện `model.transcribe()` sẽ tự động gọi process con `ffmpeg` để convert audio. Mặc dù thư mục của `imageio-ffmpeg` đã được đưa vào PATH, tệp tin binary trên Windows của package này được đặt tên theo phiên bản dạng `ffmpeg-win-x86_64-v7.1.exe` chứ không phải tên tiêu chuẩn `ffmpeg.exe`. Khi Whisper gọi subprocess chạy lệnh `ffmpeg`, hệ điều hành không tìm thấy file nào có tên chính xác là `ffmpeg.exe`, dẫn đến lỗi `WinError 2`.
- **Error Message**: 
  ```text
  Pipeline step 8 failed: [WinError 2] The system cannot find the file specified
  Pipeline failed for Job da40fcb7-adea-40de-8aee-d4310d29e325: [WinError 2] The system cannot find the file specified
  ```
- **Fix Applied**: 
  1. Cập nhật hàm `inject_ffmpeg_to_path()` trong `app/utils/ffmpeg_utils.py` để tự động tạo bản copy tiêu chuẩn với tên `ffmpeg.exe` (và `ffprobe.exe`) từ tệp nhị phân gốc của `imageio-ffmpeg` ngay trong thư mục binaries của nó nếu chưa có.
  2. Gọi `inject_ffmpeg_to_path()` ngay tại dòng đầu tiên của hàm `transcribe_audio()` trong `dubbing_engine.py` để cập nhật biến `PATH` đầy đủ cho subprocess của Whisper.
- **Prevention**: Khi tích hợp các thư viện bên thứ ba tự ý gọi shell/subprocess bên ngoài, luôn đảm bảo các biến môi trường và tên file nhị phân chạy trên môi trường Windows tương thích đầy đủ.
- **Status**: Fixed



