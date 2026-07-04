from fastapi import status
from app.models.user import User

def test_user_registration(client, db):
    # Đăng ký tài khoản mới thành công
    response = client.post(
        "/auth/register",
        data={
            "email": "test@voiceai.com",
            "password": "testpassword123",
            "full_name": "Test User"
        },
        follow_redirects=False
    )
    # Chuyển hướng sang trang đăng nhập sau khi đăng ký
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers.get("location") == "/auth/login?registered=true"

    # Kiểm tra user được lưu trong DB
    user = db.query(User).filter(User.email == "test@voiceai.com").first()
    assert user is not None
    assert user.full_name == "Test User"
    assert user.role == "admin" # Tài khoản đầu tiên đăng ký được phân quyền admin

def test_duplicate_email_registration(client, db):
    # Đăng ký user đầu tiên
    client.post(
        "/auth/register",
        data={"email": "duplicate@voiceai.com", "password": "pass", "full_name": "User 1"}
    )
    
    # Đăng ký email trùng
    response = client.post(
        "/auth/register",
        data={"email": "duplicate@voiceai.com", "password": "pass", "full_name": "User 2"}
    )
    # Trả về 200 hiển thị form kèm câu báo lỗi
    assert response.status_code == status.HTTP_200_OK
    assert "Email này đã được sử dụng." in response.text

def test_user_login_success(client, db):
    # Tạo user mẫu trong database
    client.post(
        "/auth/register",
        data={"email": "login@voiceai.com", "password": "securepassword", "full_name": "Login User"}
    )

    # Đăng nhập
    response = client.post(
        "/auth/login",
        data={"email": "login@voiceai.com", "password": "securepassword"},
        follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers.get("location") == "/dashboard"
    
    # Kiểm tra cookie JWT được thiết lập
    cookies = response.cookies
    assert "access_token" in cookies
    assert cookies.get("access_token").strip('"').startswith("Bearer ")

def test_user_login_incorrect_password(client, db):
    client.post(
        "/auth/register",
        data={"email": "wrong@voiceai.com", "password": "securepassword", "full_name": "User"}
    )

    # Đăng nhập sai mật khẩu
    response = client.post(
        "/auth/login",
        data={"email": "wrong@voiceai.com", "password": "wrongpassword"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert "Email hoặc mật khẩu không chính xác." in response.text
