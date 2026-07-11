import pytest
from app.services.link_adapters.douyin import DouyinAdapter
from app.services.link_checker import extract_clean_url

def test_extract_clean_url():
    # Test text chia sẻ từ app Douyin chứa ký tự tiếng Trung và các khoảng trắng
    shared_text = "7.20 y@K.gb H94:/ 复制打开抖音，看看【...】... https://v.douyin.com/iNeR8Xxx/ "
    cleaned = extract_clean_url(shared_text)
    assert cleaned == "https://v.douyin.com/iNeR8Xxx/"

def test_douyin_adapter_can_handle():
    adapter = DouyinAdapter()
    assert adapter.can_handle("https://v.douyin.com/iNeR8Xxx/") is True
    assert adapter.can_handle("https://www.douyin.com/video/123456789") is True
    assert adapter.can_handle("https://www.tiktok.com/@user/video/123") is True
    assert adapter.can_handle("https://www.youtube.com/watch?v=123") is False
