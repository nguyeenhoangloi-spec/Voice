# Kế hoạch triển khai: Tách giọng nói và nhạc nền thực tế bằng AI (Demucs)

Dựa trên tài liệu bàn giao `task-summary-demucs-vocal-separation.md`, tính năng tách giọng/nhạc nền bằng Demucs đang ở trạng thái **chưa thực tế triển khai** trong mã nguồn (mã nguồn hiện tại vẫn là phiên bản đơn giản hóa - copy audio và tạo file câm). 

Dưới đây là kế hoạch chi tiết để hiện thực hóa tính năng này vào hệ thống.

---

## 🎯 Mục tiêu
1. Cài đặt và tích hợp thư viện **Demucs** để tách nhạc nền và giọng nói gốc một cách thực tế.
2. Cập nhật bước 7 trong pipeline để chạy tách bằng Demucs (có cơ chế fallback tự động nếu lỗi).
3. Cập nhật bước 18 (`merge_tts_with_video`) để trộn nhạc nền đã tách thật thay vì audio gốc (tránh bị đè tiếng gốc).

---

## ⚠️ Đánh giá rủi ro (Risks & Mitigations)

> [!WARNING]
> - **Hiệu năng (CPU vs GPU)**: Demucs là mô hình Deep Learning nặng. Nếu chạy trên CPU, quá trình tách có thể mất từ 1 - 3 phút cho mỗi video 1 phút.
>   * *Giải pháp*: Tự động phát hiện nếu hệ thống có CUDA GPU để chạy chế độ tăng tốc, nếu không sẽ giới hạn luồng hoặc chạy CPU kèm thông báo log rõ ràng cho người dùng.
> - **Lần đầu tải Model (Internet)**: Demucs sẽ tải model `htdemucs` (~80MB) từ HuggingFace/Torch Hub trong lần chạy đầu tiên.
>   * *Giải pháp*: Thực hiện kiểm tra sự tồn tại của mô hình hoặc bắt lỗi mạng để fallback ngay về chế độ cũ, không làm crash pipeline.

---

## 🛠️ Đề xuất thay đổi (Proposed Changes)

### 1. Cấu hình & Cài đặt
- **[MODIFY] [requirements.txt](file:///d:/Voice_AI/requirements.txt)**: Thêm các thư viện `demucs==4.0.1`, `torch>=2.0`, `torchaudio>=2.0` để hỗ trợ chạy mô hình.

### 2. Tầng dịch vụ (AI Core)
- **[MODIFY] [dubbing_engine.py](file:///d:/Voice_AI/app/services/dubbing_engine.py)**:
  * Viết hàm `separate_vocals(video_path: str, vocal_path: str, bg_music_path: str, job_id: str) -> bool` sử dụng Demucs.
  * Sửa hàm `merge_tts_with_video()` để sử dụng đúng `bg_music_path` (nhạc nền tách thật) thay vì trích xuất lại toàn bộ audio gốc.

### 3. Tác vụ ngầm (Celery / Background Tasks)
- **[MODIFY] [dubbing_tasks.py](file:///d:/Voice_AI/app/workers/dubbing_tasks.py)**:
  * Tại **STEP 7**, gọi hàm `separate_vocals` thực tế thay vì logic copy và sinh file câm cũ.
  * Thêm log thông báo trạng thái tách thật / chế độ fallback cho người dùng.

---

## 🧪 Kế hoạch xác thực (Verification Plan)

### Kiểm thử tự động (Automated Tests)
- Tạo file test `scratch/test_demucs_separation.py` để chạy thử tách một đoạn âm thanh ngắn và kiểm tra xem có tạo ra hai file riêng biệt (vocal & no-vocal) với dung lượng hợp lệ hay không.

### Kiểm thử thủ công (Manual Verification)
1. Tải lên một video ngắn có nhạc nền và tiếng nói tiếng Anh.
2. Tạo job lồng tiếng với tùy chọn `keep_bg_music=True`.
3. Kiểm tra log của step 7 để xác nhận chạy Demucs thành công.
4. Nghe thử video kết quả: Xác nhận tiếng lồng tiếng Việt rõ ràng, nhạc nền gốc được giữ lại nhưng **hoàn toàn không còn giọng nói tiếng Anh gốc** đè ở dưới.
