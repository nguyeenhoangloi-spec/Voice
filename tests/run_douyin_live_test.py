import sys
import os

# Thêm thư mục gốc dự án vào path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.link_adapters.douyin import DouyinAdapter
from app.services.link_checker import check_url_safety, extract_clean_url

# Link video Douyin thật (chứa text bẩn chia sẻ)
shared_text = "https://www.iesdouyin.com/share/video/7657134418548542726/?region=VN&mid=7657134396299414291"

print("=== DOUYIN LIVE TEST ===")
clean_url = extract_clean_url(shared_text)
print(f"Original Text: {shared_text}")
print(f"Cleaned URL:   {clean_url}")

is_safe, error = check_url_safety(clean_url)
print(f"URL Safety:    {is_safe} ({error})")

if is_safe:
    adapter = DouyinAdapter()
    print("Extracting metadata...")
    meta = adapter.extract_metadata(clean_url)
    print("Metadata Result:")
    print(meta)
