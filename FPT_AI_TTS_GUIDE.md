# Hướng dẫn tích hợp FPT.AI TTS (Giọng Việt chuẩn nhất) vào Voice_AI

Tài liệu này hướng dẫn bạn cách thiết lập và sử dụng dịch vụ **FPT.AI Text-to-Speech (TTS)** trong dự án **Voice_AI** để đạt được chất lượng giọng đọc tiếng Việt chuẩn nhất hiện nay (vượt trội hơn so với các giọng đọc miễn phí).

---

## 1. Giới thiệu về FPT.AI TTS và các giọng đọc chuẩn nhất
FPT.AI TTS là dịch vụ chuyển đổi văn bản thành giọng nói tiếng Việt chất lượng hàng đầu, hỗ trợ đầy đủ các vùng miền (Bắc, Trung, Nam) với ngữ điệu tự nhiên, ngắt nghỉ thông minh và biểu cảm cao.

Các giọng đọc nổi bật nhất của FPT.AI được tích hợp sẵn trong hệ thống bao gồm:

| Vùng miền | Giới tính | Tên giọng đọc (FPT Voice ID) | Đặc điểm |
| :--- | :--- | :--- | :--- |
| **Miền Bắc** | Nữ | `banmai` (Mặc định) | Giọng phổ thông, tự nhiên, mượt mà và dễ nghe nhất |
| **Miền Bắc** | Nam | `leminh` | Giọng nam trầm ấm, rõ ràng, phù hợp cho tin tức |
| **Miền Bắc** | Nữ | `linhsan` | Giọng đọc báo chuyên nghiệp |
| **Miền Bắc** | Nữ | `thuminh` | Giọng nữ nhẹ nhàng, truyền cảm |
| **Miền Nam** | Nữ | `lannhi` | Giọng nữ miền Nam cực kỳ ngọt ngào, chuẩn xác và tự nhiên |
| **Miền Nam** | Nam | `giahuy` | Giọng nam miền Nam ấm áp, thân thiện |
| **Miền Trung** | Nữ | `myan` | Giọng nữ miền Trung truyền cảm, đặc trưng |

---

## 2. Các bước đăng ký và lấy API Key FPT.AI
Để sử dụng FPT.AI TTS, bạn cần đăng ký tài khoản và tạo một API Key (miễn phí ở mức cơ bản hoặc trả phí theo lưu lượng):

1. Truy cập trang quản trị FPT.AI Console: [https://console.fpt.ai](https://console.fpt.ai).
2. Đăng ký tài khoản (bằng Email hoặc Google).
3. Sau khi đăng nhập, chọn **Tạo dự án mới** (Create Project).
4. Trong giao diện dự án, tìm đến danh mục **Text to Speech** và nhấn **Kích hoạt** (Enable) dịch vụ.
5. Truy cập menu **API Keys** ở danh sách bên trái.
6. Sao chép chuỗi mã API Key được cấp (có dạng chuỗi ký tự ngẫu nhiên dài).

---

## 3. Cấu hình hệ thống Voice_AI
Hệ thống Voice_AI đã được tích hợp sẵn engine kết nối với API V5 của FPT.AI. Bạn chỉ cần bật nó lên thông qua file cấu hình `.env` ở thư mục gốc của dự án.

### Bước 3.1: Chỉnh sửa file `.env`
Mở file [`.env`](file:///d:/Voice_AI/.env) và cập nhật hai dòng cấu hình sau:

```env
# Thay đổi engine TTS từ 'edge' sang 'fpt'
TTS_ENGINE=fpt

# Điền mã API Key bạn vừa copy ở FPT.AI Console vào đây
FPT_API_KEY=chuoi_api_key_fpt_cua_ban_o_day
```

> [!NOTE]
> - Nếu bạn muốn quay lại sử dụng giọng đọc miễn phí của Microsoft Edge, chỉ cần đặt `TTS_ENGINE=edge` và để trống `FPT_API_KEY`.
> - Hãy đảm bảo `AI_MODE` trong `.env` được đặt là `real` để các API Key (OpenAI, Gemini, FPT) thực sự hoạt động thay vì giả lập (`mock`).

---

## 4. Cơ chế hoạt động trong mã nguồn
Mã nguồn xử lý FPT.AI TTS nằm chủ yếu tại file [`dubbing_engine.py`](file:///d:/Voice_AI/app/services/dubbing_engine.py).

### Quy trình Polling bất đồng bộ (Asynchronous Polling)
FPT.AI xử lý TTS dưới dạng bất đồng bộ nhằm tối ưu tài nguyên cho các đoạn văn bản dài. Hàm [`generate_fpt_tts`](file:///d:/Voice_AI/app/services/dubbing_engine.py#L150-L202) hoạt động như sau:
1. Gửi văn bản (`text`) cùng các headers cấu hình (`api_key`, `voice`, `speed`, `format="mp3"`) tới endpoint `https://api.fpt.ai/hmi/tts/v5` bằng phương thức POST.
2. API FPT.AI phản hồi ngay lập tức với mã trạng thái `200` và trả về một liên kết tải xuống tạm thời ở trường `"async"` trong JSON response.
3. Hệ thống sẽ liên tục thăm dò (polling) liên kết `"async"` này mỗi **2 giây** (tối đa 30 lần thử ~ 60 giây).
4. Khi FPT.AI hoàn tất việc tạo file âm thanh, liên kết này sẽ trả về file âm thanh nhị phân (`Content-Type` không chứa `application/json`), hệ thống sẽ tải về và lưu vào [`output_path`](file:///d:/Voice_AI/storage/audio/).

### Tự động khớp giọng (Voice Mapping)
Khi người dùng chọn giọng trong giao diện web hoặc API, hệ thống sẽ tự động ánh xạ (map) các cài đặt tương ứng thông qua hàm [`select_voice`](file:///d:/Voice_AI/app/services/dubbing_engine.py#L262-L285):
- Giọng Nữ Miền Bắc $\rightarrow$ `banmai`
- Giọng Nữ Miền Nam $\rightarrow$ `lannhi`
- Giọng Nữ Miền Trung $\rightarrow$ `myan`
- Giọng Nam Miền Bắc $\rightarrow$ `leminh`
- Giọng Nam Miền Nam $\rightarrow$ `giahuy`

---

## 5. Kiểm tra hoạt động
Sau khi đã điền API Key và đổi cấu hình, hãy khởi động lại Web Server và Celery worker (nếu đang chạy):

```powershell
# Kích hoạt môi trường conda
conda activate voiceai

# Chạy lại web server
python run.py
```

Hãy thực hiện một lượt lồng tiếng video thử nghiệm để trải nghiệm chất lượng giọng đọc vượt trội từ FPT.AI. Nếu gặp bất kỳ lỗi nào liên quan đến API FPT, hãy kiểm tra file [`ERRORS.md`](file:///d:/Voice_AI/ERRORS.md) hoặc log server để biết chi tiết mã lỗi trả về từ FPT.AI API.
