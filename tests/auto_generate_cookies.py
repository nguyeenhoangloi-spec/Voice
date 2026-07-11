import requests
import time
import os

def generate_douyin_cookies():
    url = "https://www.douyin.com/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Referer': 'https://v.douyin.com/'
    }
    
    print("Sending request to Douyin to retrieve guest cookies...")
    session = requests.Session()
    try:
        # Gửi request để lấy các cookie cơ bản từ trang chủ Douyin
        response = session.get(url, headers=headers, timeout=10)
        print(f"Response Status Code: {response.status_code}")
    except Exception as e:
        print(f"Request failed: {e}")
        return False
    
    cookies = session.cookies
    if not cookies:
        print("No cookies returned from Douyin.")
        return False
        
    print(f"Retrieved {len(cookies)} cookies:")
    for cookie in cookies:
        print(f" - {cookie.name}: {cookie.value[:30]}... (domain: {cookie.domain})")
        
    # Ghi cookies ra định dạng Netscape cookies.txt
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cookie_file_path = os.path.join(project_root, "cookies.txt")
    
    try:
        with open(cookie_file_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This file is generated automatically by VoiceAI to bypass Douyin restrictions.\n\n")
            
            for cookie in cookies:
                domain = cookie.domain
                # Cấu hình định dạng Netscape
                include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
                path = cookie.path or "/"
                secure = "TRUE" if cookie.secure else "FALSE"
                expiration = str(cookie.expires) if cookie.expires else str(int(time.time()) + 315360000) # 10 years fallback
                name = cookie.name
                value = cookie.value
                
                f.write(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiration}\t{name}\t{value}\n")
                
        print(f"Successfully generated cookies.txt at: {cookie_file_path}")
        return True
    except Exception as e:
        print(f"Failed to write cookies file: {e}")
        return False

if __name__ == "__main__":
    generate_douyin_cookies()
