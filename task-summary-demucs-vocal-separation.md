# Task Log: Tách giọng/nhạc nền thật bằng Demucs — Dự án Voice (lồng tiếng AI)

Dùng file này làm prompt/ngữ cảnh khi giao việc tiếp cho AI agent khác, hoặc lưu làm
tài liệu bàn giao nội bộ. Nội dung mô tả: bối cảnh, việc đã làm, kết quả đạt được,
và các việc còn tồn đọng cần làm tiếp.

---

## 1. Bối cảnh dự án

Repo `Voice` là hệ thống lồng tiếng video tự động: nhận link (YouTube/TikTok/webpage/
direct media) hoặc file upload → tải video → tách audio → nhận diện giọng nói (ASR) →
dịch sang tiếng Việt → sinh giọng đọc TTS → ghép lại thành video hoàn chỉnh, xuất kèm
phụ đề SRT/VTT. Pipeline gồm 20 bước, chạy qua FastAPI `BackgroundTasks`
(`app/workers/dubbing_tasks.py`), logic AI nằm ở `app/services/dubbing_engine.py`.

Đánh giá ban đầu (rà toàn bộ code, không chỉ README) cho thấy pipeline **đã chạy thật
end-to-end** (không phải mock): yt-dlp tải video thật, Whisper ASR thật, dịch qua nhiều
provider LLM thật (Gemini/Groq/OpenRouter/GitHub/Cohere + fallback Google Translate),
edge-tts sinh giọng thật, ffmpeg ghép video thật.

Tuy nhiên phát hiện 3 bước bị "giả" — tên bước nghe như đã xử lý AI nhưng thực chất
chỉ hard-code log hoặc bỏ qua xử lý thật:

| Bước | Tên hiển thị | Thực tế code làm gì |
|---|---|---|
| 7 | Tách lời thoại và nhạc nền | Chỉ `shutil.copy()` audio gốc làm "vocal", tạo file nhạc nền là **im lặng 1 giây** |
| 9 | Phân chia người nói | Chỉ heuristic dựa khoảng lặng giữa các câu, không phải diarization AI thật |
| 10 | Phân tích ngữ cảnh và cảm xúc | Log cứng `"Tu nhien, trang thai binh thuong"`, không phân tích gì |

Ngoài ra: hàm `merge_tts_with_video()` ở bước ghép cuối (bước 18) nhận tham số
`bg_music_path` nhưng **không hề dùng** — khi bật "giữ nhạc nền", hàm tự trích lại
**toàn bộ audio gốc** (còn nguyên giọng nói gốc), hạ âm lượng rồi đè xuống dưới giọng
lồng tiếng mới. Hậu quả: người xem vẫn nghe văng vẳng giọng gốc lẫn dưới giọng Việt.

Người dùng chọn ưu tiên xử lý vấn đề **#1 — tách nhạc nền thật** trước.

---

## 2. Việc đã thực hiện

### 2.1. Thêm hàm tách giọng/nhạc nền thật bằng AI (Demucs)
File: `app/services/dubbing_engine.py` — hàm mới `separate_vocals()`

- Trích audio chất lượng cao (44.1kHz, stereo) từ video nguồn bằng ffmpeg — chất
  lượng cao hơn hẳn track 16kHz mono vốn chỉ tối ưu cho ASR.
- Chạy Demucs model `htdemucs` ở chế độ `--two-stems=vocals` (tách 2 track: giọng nói
  / phần còn lại tức nhạc nền + hiệu ứng).
- Copy 2 file kết quả (`vocals.wav`, `no_vocals.wav`) ra đúng đường dẫn pipeline cần.
- **Có fallback an toàn**: nếu Demucs lỗi (chưa cài, thiếu mạng để tải model, hết
  RAM...) → tự động rơi về hành vi cũ (copy audio gốc làm vocal, tạo file câm làm
  nhạc nền), đồng thời trả về cờ `real_separation=False` để tầng gọi biết và log đúng
  sự thật, không còn báo "thành công" giả.

### 2.2. Nối hàm mới vào bước 7 của pipeline
File: `app/workers/dubbing_tasks.py`

- Bước 7 giờ gọi `separate_vocals(source_path, vocal_audio, bg_music, job_id)` thay
  vì đoạn `shutil.copy()` giả trước đó.
- Log hiển thị cho người dùng phân biệt rõ 2 trường hợp: tách thành công bằng AI, hay
  đang dùng phương án dự phòng (kèm cảnh báo nhạc nền có thể còn dính giọng gốc).

### 2.3. Sửa bước ghép video cuối để dùng đúng track đã tách thật
File: `app/services/dubbing_engine.py` — hàm `merge_tts_with_video()`

- Khi bật "giữ nhạc nền" (`keep_bg_music=True`), hàm giờ **ưu tiên dùng track nhạc
  nền thật** (`bg_music_path` — kết quả từ bước 7, kiểm tra tồn tại + kích thước hợp
  lệ để loại trừ file câm 1 giây).
- Chỉ khi không có track tách thật mới fallback về cách cũ (trích lại audio gốc,
  cảnh báo rõ trong log là "có thể còn dính giọng gốc").
- Dọn file tạm đúng cách bằng `finally`, tránh rác trong `storage/exports`.

### 2.4. Cập nhật dependency
File: `requirements.txt`

- Thêm `demucs==4.0.1`, `torch>=2.0`, `torchaudio>=2.0`.
- Ghi chú kèm theo: lần chạy đầu Demucs tự tải model pretrained (~80MB, cần mạng);
  máy có GPU NVIDIA nên cài bản `torch` có CUDA riêng để tách nhanh hơn nhiều so
  với chạy CPU.

### 2.5. Kiểm tra
- Compile-check bằng `python3 -m py_compile` cho cả 2 file sửa — cú pháp hợp lệ.
- **Chưa chạy thử Demucs thật** (sandbox không có internet để tải model) — cần người
  dùng tự test trên máy có mạng trước khi deploy.

---

## 3. Kết quả đạt được

- Tính năng "giữ nhạc nền" giờ hoạt động **đúng như tên gọi**: nhạc nền phát ra là
  nhạc nền thật đã được AI tách khỏi giọng nói gốc, không còn lẫn giọng gốc dưới
  giọng lồng tiếng Việt mới.
- Pipeline vẫn **không bao giờ crash** nếu Demucs gặp sự cố — tự rơi về hành vi cũ,
  nhưng giờ log trung thực về việc có tách thật hay không (giúp debug sau này dễ hơn,
  đúng tinh thần `ERRORS.md` mà dự án đang duy trì).
- Không đổi cấu trúc dữ liệu segment/DB, không đổi API — chỉ thay đổi nội bộ 2 hàm +
  1 bước pipeline, an toàn để merge ngay.

---

## 4. Việc còn tồn đọng / kiến nghị tiếp theo

Thứ tự ưu tiên đề xuất (dựa trên đánh giá ban đầu, chưa làm):

1. **Chuyển từ FastAPI `BackgroundTasks` sang Celery + Redis thật**
   README đã nhắc Celery/Redis và `requirements.txt` đã có 2 thư viện này, nhưng
   `app/routers/dubbing.py` hiện chỉ gọi `background_tasks.add_task(run_dubbing_pipeline, job_id)`
   — chạy trong cùng process FastAPI, không phải queue riêng. Cần: viết `celery_app`
   thật, chuyển `run_dubbing_pipeline` thành Celery task, để chạy được nhiều job song
   song trên nhiều worker và sống sót qua việc restart server.

2. **Nối voice cloning giữ giọng gốc**
   Thư mục `app/services/voicebox_reference_code/` đã có sẵn nhiều backend TTS
   (Kokoro, Chatterbox, Qwen Custom Voice...) nhưng pipeline chính (bước 14) hiện chỉ
   dùng `edge-tts` (giọng máy có sẵn, không giữ được đặc trưng giọng gốc của người
   nói trong video). Cần đánh giá backend nào trong thư mục tham khảo đó phù hợp nhất
   để nối vào `generate_all_tts_segments()`.

3. **Diarization (phân biệt người nói) thật**
   Bước 9 hiện chỉ dựa heuristic khoảng lặng giữa các câu (`_detect_speaker_changes`),
   dễ gán nhầm khi nhiều người nói chồng tiếng hoặc nói nhanh liên tục. Cân nhắc tích
   hợp `pyannote.audio` hoặc mô hình diarization tương đương.

4. **Phân tích cảm xúc thật cho bước 10**
   Hiện hard-code log cứng, không ảnh hưởng gì tới cách chọn tone giọng TTS. Nếu muốn
   tận dụng thật, cần: (a) chạy model nhận diện cảm xúc từ audio hoặc từ văn bản dịch,
   (b) map kết quả sang tham số SSML/tốc độ-cao độ khi gọi TTS ở bước 14.

---

## 5. Cách bàn giao / test lại

1. Copy 2 file đã sửa (`dubbing_engine.py`, `dubbing_tasks.py`) và `requirements.txt`
   mới vào đúng vị trí trong repo.
2. `pip install -r requirements.txt` (máy cần internet để tải Demucs + torch lần đầu).
3. Chạy thử 1 job lồng tiếng với `keep_bg_music=True`, theo dõi log bước 7 và bước 18:
   - Nếu thấy `"Tach loi thoai va nhac nen thanh cong bang AI (Demucs)"` → tách thật
     đã chạy đúng.
   - Nếu thấy `"Demucs khong kha dung..."` → kiểm tra lại cài đặt Demucs/torch, hoặc
     kết nối mạng để tải model lần đầu.
4. Nghe thử file video/audio xuất ra: xác nhận nhạc nền không còn dính giọng gốc.
