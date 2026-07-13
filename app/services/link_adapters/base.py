import abc

class BaseAdapter(abc.ABC):
    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:
        """Kiểm tra xem adapter này có xử lý được URL này không"""
        pass

    @abc.abstractmethod
    def extract_metadata(self, url: str) -> dict:
        """Trích xuất thông tin tiêu đề, thời lượng, ảnh thumbnail, định dạng..."""
        pass

    @abc.abstractmethod
    def download(self, url: str, output_path: str, **kwargs) -> str:
        """Tải nội dung media từ URL và lưu vào output_path.
        
        Supported kwargs:
            clip_start (str|None): "HH:MM:SS" — start time for partial download
            clip_end   (str|None): "HH:MM:SS" — end time for partial download
        """
        pass
