import socket
import ipaddress
import re
from urllib.parse import urlparse

# Dải IP nội bộ và riêng tư cần chặn
PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private class A
    ipaddress.ip_network("172.16.0.0/12"),    # Private class B
    ipaddress.ip_network("192.168.0.0/16"),   # Private class C
    ipaddress.ip_network("169.254.169.254/32"), # Cloud metadata endpoint
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]

def extract_clean_url(text: str) -> str:
    """
    Trích xuất URL sạch đầu tiên trong văn bản thô (ví dụ văn bản chia sẻ của TikTok).
    Nếu không tìm thấy URL, trả về chính chuỗi văn bản ban đầu (sau khi loại bỏ khoảng trắng).
    """
    if not text:
        return ""
    # Tìm kiếm URL bắt đầu bằng http:// hoặc https:// (loại bỏ ký tự phi Latinh/tiếng Trung sát sau URL)
    urls = re.findall(r'https?://[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+', text)
    if urls:
        url = urls[0]
        # Loại bỏ các ký tự dấu câu thừa ở cuối URL nếu có
        url = url.rstrip('.,;)]}「」“”\'"')
        return url
    return text.strip()

def check_url_safety(url: str) -> tuple[bool, str]:
    """
    Kiểm tra xem URL có hợp lệ và an toàn (chống SSRF) không.
    Trả về (is_safe, error_message).
    """
    try:
        # Tự động làm sạch và trích xuất URL thực tế
        url = extract_clean_url(url)
        parsed_url = urlparse(url)
        
        # Chỉ cho phép giao thức http và https
        if parsed_url.scheme not in ["http", "https"]:
            return False, "Chỉ hỗ trợ giao thức HTTP và HTTPS."
            
        hostname = parsed_url.hostname
        if not hostname:
            return False, "Tên miền không hợp lệ."
            
        # Giải phân giải hostname thành các IP address
        try:
            ip_addresses = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False, "Không thể phân giải tên miền."
            
        for addr in ip_addresses:
            ip_str = addr[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            
            # Kiểm tra xem IP có thuộc dải mạng private nào không
            for network in PRIVATE_NETWORKS:
                if ip_obj in network:
                    return False, f"Truy cập vào địa chỉ IP nội bộ bị cấm: {ip_str}"
                    
        return True, "URL an toàn và hợp lệ."
        
    except Exception as e:
        return False, f"Lỗi kiểm tra URL: {str(e)}"
