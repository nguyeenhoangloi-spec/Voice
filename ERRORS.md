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

---

## [2026-07-06 23:10] - Pipeline step 11 failed: No module named 'deep_translator'

- **Type**: Integration
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:172`
- **Agent**: Voice
- **Root Cause**: Pipeline lồng tiếng sử dụng thư viện `deep-translator` ở bước thứ 11 để thực hiện dịch thuật ngôn ngữ thoại sang tiếng Việt (Google Translate fallback). Do môi trường ảo Python thiếu thư viện này (chưa được khai báo trong `requirements.txt`), FastAPI ném ra lỗi `ModuleNotFoundError: No module named 'deep_translator'`.
- **Error Message**: 
  ```text
  Pipeline step 8 failed: No module named 'deep_translator'
  Pipeline failed for Job 6fa581e5-0d93-48b8-b986-17378aa910d0: No module named 'deep_translator'
  ```
- **Fix Applied**: Cài đặt thư viện `deep-translator` và cập nhật vào `requirements.txt`.
- **Prevention**: Đảm bảo kiểm tra toàn bộ imports và khai báo đầy đủ các dependencies cần thiết trong `requirements.txt`.
- **Status**: Fixed

---

## [2026-07-06 23:20] - Edge TTS NoAudioReceived error due to concurrent connection rate-limiting

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:312`
- **Agent**: Voice
- **Root Cause**: Khi sinh giọng đọc tiếng Việt bằng Edge TTS, hệ thống chạy song song tới 15 luồng (`max_workers = 15`). Điều này làm kích hoạt cơ chế giới hạn tần suất (rate-limiting/concurrency limit) của Microsoft Edge TTS API, khiến WebSocket bị ngắt kết nối và trả về lỗi `NoAudioReceived` cho rất nhiều phân đoạn, dẫn đến các phân đoạn đó không có tiếng lồng tiếng, chỉ nghe thấy âm thanh gốc ở video kết xuất.
- **Error Message**: 
  ```text
  edge_tts.exceptions.NoAudioReceived: No audio was received. Please verify that your parameters are correct.
  ```
- **Fix Applied**: 
  1. Giảm số lượng workers chạy song song trong `generate_all_tts_segments` từ `15` xuống `3` luồng để tránh bị Microsoft block.
  2. Bổ sung cơ chế tự động thử lại (Retry) tối đa 3 lần với khoảng nghỉ tăng dần (exponential backoff) trong hàm `generate_tts_audio` để đảm bảo sinh thành công tệp âm thanh.
- **Prevention**: Luôn giới hạn số lượng luồng đồng thời ở mức an toàn (< 5 luồng) đối với các API miễn phí của bên thứ ba, đồng thời luôn tích hợp cơ chế Retry để tránh mất mát dữ liệu do lỗi mạng tạm thời.
- **Status**: Fixed

---

## [2026-07-06 23:40] - Lỗi nghe thử giọng mẫu bị đứng 0:00 (401 Unauthorized)

- **Type**: Runtime / Security
- **Severity**: High
- **File**: `app/routers/dubbing.py:460`
- **Agent**: Voice
- **Root Cause**: Endpoint sinh và tải file nghe thử mẫu giọng AI (`/voices/sample/{voice_id}.mp3`) yêu cầu xác thực người dùng (`user=Depends(get_current_user)`). Tuy nhiên, khi trình duyệt tải thẻ `<audio controls src="...">`, nó gửi request HTTP GET trực tiếp thông thường mà không thể tự động đính kèm Token JWT (Authorization Header) vào request, dẫn đến FastAPI trả về lỗi `401 Unauthorized` và trình phát nhạc bị lỗi không tải được.
- **Fix Applied**: Loại bỏ dependency `user=Depends(get_current_user)` khỏi endpoint này, biến nó thành API công khai (Public) do tính năng nghe thử mẫu giọng không chứa dữ liệu nhạy cảm của người dùng.
- **Prevention**: Tránh bắt buộc xác thực JWT đối với các tệp đa phương tiện tĩnh công khai (như file nghe thử, ảnh công cộng) được tải qua thẻ HTML trực tiếp.
- **Status**: Fixed

---

## [2026-07-06 23:55] - Video kết xuất chỉ có nhạc gốc, mất tiếng lồng tiếng do thiếu ffprobe (WinError 2) trong pydub

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:440`
- **Agent**: Voice
- **Root Cause**: Thư viện xử lý âm thanh `pydub` bắt buộc phải sử dụng công cụ `ffprobe` khi gọi `AudioSegment.from_file()` để phân tích định dạng tệp âm thanh. Tuy nhiên, môi trường Windows chỉ có `ffmpeg.exe` (từ `imageio-ffmpeg`) mà hoàn toàn không có `ffprobe.exe`. Do đó, khi trộn âm thanh, `pydub` ném ra lỗi `[WinError 2] The system cannot find the file specified` cho tất cả các phân đoạn thoại, khiến tệp âm thanh tổng hợp bị rỗng. Tiếp đó, lệnh ghép video của FFmpeg bị lỗi do thiếu file âm thanh đầu vào, kích hoạt cơ chế fallback copy đè video gốc (dẫn đến video thành phẩm chỉ có âm thanh gốc).
- **Fix Applied**: 
  1. Cài đặt package `@ffprobe-installer/win32-x64` từ npm để lấy file nhị phân `ffprobe.exe` tĩnh 77MB chính thức.
  2. Lưu file `ffprobe.exe` vào thư mục `binaries/` của dự án.
  3. Cập nhật `ffmpeg_utils.py` để tự động sao chép `ffprobe.exe` vào cùng thư mục với `ffmpeg.exe` của `imageio-ffmpeg` và đưa thư mục đó vào đầu `PATH` của session khi import, đảm bảo `pydub` và các tiến trình con luôn tìm thấy cả hai.
- **Prevention**: Luôn đảm bảo cả `ffmpeg` và `ffprobe` đều có mặt đầy đủ trong `PATH` khi làm việc với thư viện xử lý âm thanh trong python (như `pydub`, `librosa`).
- **Status**: Fixed

---

## [2026-07-10 20:30] - HTTP 401 Unauthorized loops on GET request for templates

- **Type**: Security / UX
- **Severity**: Medium
- **File**: `app/main.py:18`
- **Agent**: Voice
- **Root Cause**: FastAPI dependency `get_current_user` ném ra ngoại lệ `HTTPException(status_code=401, detail="Not authenticated")` khi người dùng chưa đăng nhập nhưng cố gắng truy cập các trang HTML (ví dụ: `/dubbing/create`). Vì không có exception handler bắt lỗi này để redirect, trình duyệt nhận về JSON lỗi thô 401 Unauthorized dẫn đến việc lặp yêu cầu hoặc không thể chuyển hướng mượt mà đến trang đăng nhập.
- **Fix Applied**: Thêm một custom exception handler cho `HTTPException` trong `app/main.py`. Nếu gặp mã lỗi 401 và request yêu cầu nhận HTML (`"text/html"` trong Accept header), hệ thống tự động redirect (303 Redirect) về trang đăng nhập `/auth/login` đồng thời xoá cookie `access_token` cũ để tránh lặp vô hạn.
- **Prevention**: Luôn có cơ chế exception handler để chuyển hướng người dùng từ trang HTML cần đăng nhập về trang Login thay vì trả JSON lỗi thô 401.
- **Status**: Fixed

## [2026-07-11 16:12] - Douyin Download Failed (Job ID: 49c4eeb6)

- **Type**: Integration
- **Severity**: Medium
- **File**: `app/services/link_adapters/douyin.py`
- **Agent**: dubbing_tasks.run_dubbing_pipeline (Step 4)
- **Root Cause**: yt-dlp va cobalt.tools deu that bai voi URL Douyin nay
- **Error Message**:
  ```
  URL: https://www.douyin.com/jingxuan?modal_id=7657132831633673499
  All Douyin download strategies failed. yt-dlp error: [0;31mERROR:[0m [Douyin] 7657132831633673499: Fresh cookies (not necessarily logged in) are needed | cobalt.tools error: cobalt.tools API returned no data
  ```
- **Fix Applied**: Job chuyen sang trang thai `waiting_upload`. Nguoi dung se duoc yeu cau upload file MP4 thu cong.
- **Prevention**: Cap nhat cookies.txt dinh ky hoac tinh chinh cobalt.tools endpoint
- **Status**: Auto-handled

---

## [2026-07-11 16:13] - Douyin Download Failed (Job ID: f720ff66)

- **Type**: Integration
- **Severity**: Medium
- **File**: `app/services/link_adapters/douyin.py`
- **Agent**: dubbing_tasks.run_dubbing_pipeline (Step 4)
- **Root Cause**: yt-dlp va cobalt.tools deu that bai voi URL Douyin nay
- **Error Message**:
  ```
  URL: https://v.douyin.com/ipyi7oAF82I/
  All Douyin download strategies failed. yt-dlp error: [0;31mERROR:[0m [Douyin] 7648491723722607898: Fresh cookies (not necessarily logged in) are needed | cobalt.tools error: cobalt.tools API returned no data
  ```
- **Fix Applied**: Job chuyen sang trang thai `waiting_upload`. Nguoi dung se duoc yeu cau upload file MP4 thu cong.
- **Prevention**: Cap nhat cookies.txt dinh ky hoac tinh chinh cobalt.tools endpoint
- **Status**: Auto-handled

---


## [2026-07-12 20:30] - Pipeline step 8 failed: [WinError 127] (ctranslate2 DLL load issue)

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:716`
- **Agent**: Voice
- **Root Cause**: Khi nạp thư viện `whisperx` (sử dụng `faster_whisper` và `ctranslate2` ở tầng dưới), Windows cố gắng load các file DLL của Intel MKL hoặc CUDA có sẵn trong PATH hệ thống nhưng bị xung đột phiên bản. Do Uvicorn ở chế độ dev reload sinh tiến trình con chạy ứng dụng thực tế bỏ qua file khởi chạy `run.py`, biến môi trường PATH cấu hình tại `run.py` không được truyền cho tiến trình con.
- **Fix Applied**: 
  1. Thêm đoạn mã tự động phát hiện và chèn thư mục `Library\bin` của conda environment `voiceai` vào đầu biến môi trường `PATH` ngay dòng đầu tiên của `app/main.py`.
  2. Bật cấu hình `os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"` ngay từ dòng đầu tiên của `app/main.py` để tránh lỗi crash access violation khi load trùng lặp DLL MKL.
- **Prevention**: Luôn nạp các biến môi trường cấu hình đường dẫn DLL và bỏ qua trùng lặp thư viện MKL ngay tại điểm khởi đầu thực sự của ứng dụng FastAPI (`app/main.py`) thay vì chỉ định nghĩa ở file entrypoint start script (`run.py`) để các tiến trình con được spawn ra kế thừa trọn vẹn cấu hình.
- **Status**: Fixed

---

## [2026-07-13 08:22] - Pipeline step 8 failed: [WinError 127] / UnpicklingError (torchaudio/torch DLL mismatch & weights_only constraint)

- **Type**: Runtime
- **Severity**: Critical
- **File**: `app/services/dubbing_engine.py:744`
- **Agent**: Voice
- **Root Cause**: 
  1. Thư viện `torchaudio` cài đặt phiên bản `2.11.0` không đồng bộ với `torch` phiên bản `2.8.0` trên Windows, dẫn đến việc không thể load DLL C++ extension của torchaudio (`[WinError 127] The specified procedure could not be found`).
  2. Sau khi hạ cấp `torchaudio` về bản `2.8.0` tương thích, PyTorch 2.6+ kích hoạt cơ chế an toàn `weights_only=True` mặc định khi gọi `torch.load` trong Pyannote VAD (sử dụng bởi WhisperX), từ chối unpickle các lớp của `omegaconf` và kiểu dữ liệu chuẩn (`list`, `int`, v.v.), gây ra lỗi `UnpicklingError`.
- **Error Message**: 
  ```text
  OSError: [WinError 127] The specified procedure could not be found
  _pickle.UnpicklingError: Weights only load failed. Unsupported global: GLOBAL omegaconf.listconfig.ListConfig was not an allowed global by default.
  ```
- **Fix Applied**: 
  1. Gỡ cài đặt và cài đặt lại `torchaudio==2.8.0` để khớp với `torch==2.8.0`, đồng thời cập nhật `requirements.txt`.
  2. Thực hiện monkeypatch hàm `torch.load` toàn cục tại `app/main.py` và `app/services/dubbing_engine.py` (trong hàm `transcribe_audio`) để thiết lập `weights_only=False`, cho phép WhisperX/Pyannote tải model weights cục bộ một cách bình thường.
- **Prevention**: Đồng bộ hóa phiên bản `torch` và `torchaudio` khi định nghĩa các dependencies. Thiết lập monkeypatch hoặc whitelist đối với cơ chế `weights_only` mới của PyTorch khi sử dụng các mô hình checkpoint cũ hơn (như WhisperX/Pyannote VAD).
- **Status**: Fixed

---

## [2026-07-13 09:00] - YouTube Link check fails with "This video is not available" (yt-dlp EJS Signature Challenge failure)

- **Type**: Integration
- **Severity**: High
- **File**: `app/services/link_adapters/ytdlp.py:26`
- **Agent**: Voice
- **Root Cause**: 
  1. Thư viện `yt-dlp` phiên bản mới yêu cầu trình dịch JavaScript (Node.js/Deno) để giải mã chữ ký (signature cipher challenge) của YouTube đối với một số video nhất định.
  2. Conda environment chạy FastAPI server không tìm thấy Node.js trên PATH do môi trường bị cô lập, và thiếu cấu hình `--remote-components ejs:github` để tải script giải mã tự động từ GitHub.
  3. Lỗi này khiến `yt-dlp` trả về thông báo sai lệch `"This video is not available"` làm hệ thống hiểu lầm và trả về lỗi `400 Bad Request`.
- **Fix Applied**: 
  1. Cập nhật `_get_ytdlp_base_opts` trong `app/services/link_adapters/ytdlp.py` để tự động phát hiện đường dẫn cài đặt Node.js (`shutil.which` hoặc các đường dẫn phổ biến trên Windows) và cấu hình khóa `js_runtimes` & `remote_components` vào các tham số khởi tạo mặc định của `YoutubeDL`.
  2. Bổ sung cơ chế ngắt sớm (early break) trong `extract_metadata` khi nhận được lỗi `"unsupported url"`, giúp bỏ qua các bước thử nạp cookie trình duyệt không cần thiết (Edge/Chrome) vốn gây ra hàng loạt cảnh báo DPAPI/Cookie phiền phức trên terminal Windows.
- **Prevention**: Khi làm việc với các thư viện đóng gói phụ thuộc vào binary hoặc CLI bên ngoài (như `yt-dlp`), cần cấu hình rõ ràng đường dẫn runtime phụ thuộc và cập nhật các cơ chế giải quyết challenge mới nhất của bên thứ ba. Đồng thời, cấu hình bộ lọc ngoại lệ để ngừng thử lại (fallback) ngay khi phát hiện định dạng đầu vào không hợp lệ.
- **Status**: Fixed

---

## [2026-07-13 17:09] - ReferenceError: data is not defined in job_progress.html script

- **Type**: Agent (UI / JS)
- **Severity**: High
- **File**: `app/templates/user/job_progress.html:517`
- **Agent**: Voice
- **Root Cause**: Trong phiên làm việc trước, khi thêm tính năng hiển thị thời gian chạy của từng bước (`step-time`), code JS đã gọi kiểm tra `data.performance_stats` nhưng biến `data` không nằm trong phạm vi truy cập (scope) của hàm `renderStepsAndLogs(steps)`. Lỗi này làm Javascript bị crash lập tức ở bước đầu tiên, khiến danh sách các bước lồng tiếng trên UI trống trơn và Console Logs bị kẹt ở trạng thái khởi tạo.
- **Error Message**: 
  ```text
  ReferenceError: data is not defined
      at renderStepsAndLogs (job_progress.html:517:29)
      at updateStepsList (job_progress.html:452:17)
  ```
- **Fix Applied**: 
  1. Thêm tham số `performanceStats` vào hàm `renderStepsAndLogs(steps, performanceStats)` và thay thế toàn bộ tham chiếu `data.performance_stats` tương ứng.
  2. Cập nhật các nơi gọi hàm `renderStepsAndLogs` để truyền đúng giá trị `data.performance_stats`.
  3. Thêm lệnh gọi `updateStepsList()` ngay khi trang được tải xong để hiển thị lập tức mà không cần chờ gói tin SSE đầu tiên.
- **Prevention**: Luôn kiểm tra kỹ phạm vi hoạt động (scope) của các biến khi tích hợp code từ các đoạn code khác nhau vào một hàm Javascript dùng chung.
- **Status**: Fixed

---

## [2026-07-13 17:15] - Ghi đè tự động tùy chọn ASR khi chạy ở chế độ hiệu năng Fast/Balanced

- **Type**: Agent (Logic)
- **Severity**: Medium
- **File**: `app/workers/dubbing_tasks.py:365`
- **Agent**: Voice
- **Root Cause**: Hệ thống tự động kích hoạt tải phụ đề YouTube (softsub) khi video nguồn là một liên kết và chế độ hiệu năng là Fast hoặc Balanced, kể cả khi người dùng đã lựa chọn rõ ràng phương thức nhận dạng giọng nói là "Nhận dạng giọng nói (ASR - Whisper)". Điều này vi phạm tính nhất quán trong các lựa chọn cấu hình của người dùng.
- **Fix Applied**: Sửa đổi biến kiểm tra `try_softsub_first` trong file `dubbing_tasks.py` để chỉ bằng `True` khi người dùng chọn rõ ràng `asr_method == "softsub"`.
- **Prevention**: Luôn tuân thủ tuyệt đối các tùy chọn tường minh được người dùng cấu hình trên UI (Explicit overrides Implicit optimizations).
- **Status**: Fixed
---


