// Quản lý các tương tác giao diện chính
document.addEventListener("DOMContentLoaded", () => {
    // 1. Quản lý trạng thái Sidebar (Thu gọn / Mở rộng)
    const container = document.querySelector(".app-container");
    const sidebar = document.querySelector(".app-sidebar");
    const toggleBtn = document.getElementById("sidebar-toggle");
    
    // Tạo lớp phủ (Overlay) cho Mobile nếu chưa có
    let overlay = document.querySelector(".sidebar-overlay");
    if (!overlay && container) {
        overlay = document.createElement("div");
        overlay.className = "sidebar-overlay";
        document.body.appendChild(overlay);
    }
    
    // Đọc trạng thái sidebar từ LocalStorage
    const isCollapsed = localStorage.getItem("voiceai-sidebar-collapsed") === "true";
    if (isCollapsed && container && window.innerWidth > 768) {
        container.classList.add("sidebar-collapsed");
    }
    
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            if (window.innerWidth <= 768) {
                // Trên Mobile: Mở/Đóng dạng Drawer
                sidebar.classList.toggle("active");
                overlay.classList.toggle("active");
            } else {
                // Trên PC: Thu gọn/Mở rộng
                container.classList.toggle("sidebar-collapsed");
                localStorage.setItem("voiceai-sidebar-collapsed", container.classList.contains("sidebar-collapsed"));
            }
        });
    }
    
    // Đóng drawer khi chạm vào lớp phủ overlay
    if (overlay) {
        overlay.addEventListener("click", () => {
            sidebar.classList.remove("active");
            overlay.classList.remove("active");
        });
    }

    // Đóng drawer khi bấm phím Escape
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if (sidebar && sidebar.classList.contains("active")) {
                sidebar.classList.remove("active");
                overlay.classList.remove("active");
            }
        }
    });
});

// 2. Hệ thống Toast Notifications
function showToast(message, type = "info", duration = 3000) {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }
    
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let iconSvg = "";
    if (type === "success") {
        iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
    } else if (type === "danger") {
        iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    } else if (type === "warning") {
        iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    } else {
        iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;
    }
    
    toast.innerHTML = `
        <div class="toast-icon">${iconSvg}</div>
        <div class="toast-text">${message}</div>
    `;
    
    container.appendChild(toast);
    
    // Tự động xóa sau thời gian xác định
    setTimeout(() => {
        toast.style.animation = "slideOut 0.25s forwards";
        toast.addEventListener("animationend", () => {
            toast.remove();
            if (container.children.length === 0) {
                container.remove();
            }
        });
    }, duration);
}

// Thêm keyframe animation dynamically cho slideOut
if (!document.getElementById("toast-animation-styles")) {
    const style = document.createElement("style");
    style.id = "toast-animation-styles";
    style.innerHTML = `
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
    `;
    document.head.appendChild(style);
}
