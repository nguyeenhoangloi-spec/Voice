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
        if (toggleBtn) toggleBtn.classList.add("is-collapsed");
    }
    
    // Gỡ bỏ class khóa tạm thời ở html để trả lại transition mượt mà
    document.documentElement.classList.remove("sidebar-collapsed-init");
    
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            if (window.innerWidth <= 768) {
                // Trên Mobile: Mở/Đóng dạng Drawer
                sidebar.classList.toggle("active");
                overlay.classList.toggle("active");
            } else {
                // Trên PC: Thu gọn/Mở rộng + xoay icon 180°
                const nowCollapsed = container.classList.toggle("sidebar-collapsed");
                toggleBtn.classList.toggle("is-collapsed", nowCollapsed);
                localStorage.setItem("voiceai-sidebar-collapsed", nowCollapsed);
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

// ==========================================
// 3. Hệ thống Custom PJAX (SPA Routing)
// ==========================================
class PjaxRouter {
    constructor() {
        this.pageListeners = [];
        this.pageIntervals = [];
        this.pageTimeouts = [];
        this.pageEventSources = [];
        this.isExecutingScripts = false;
        
        this.initHooks();
        this.initProgressBar();
        this.bindEvents();
    }

    initHooks() {
        const self = this;
        
        // Hook EventTarget.prototype.addEventListener
        const originalAddEventListener = EventTarget.prototype.addEventListener;
        EventTarget.prototype.addEventListener = function(type, listener, options) {
            if (self.isExecutingScripts) {
                // Nếu là sự kiện DOMContentLoaded hoặc load, kích hoạt thực thi callback ngay lập tức
                if (type === "DOMContentLoaded" || type === "load") {
                    try {
                        if (typeof listener === "function") {
                            listener.call(this);
                        } else if (listener && typeof listener.handleEvent === "function") {
                            listener.handleEvent({ type, target: this });
                        }
                    } catch(e) {
                        console.error("Error executing dynamic listener:", e);
                    }
                    return; // Không đăng ký sự kiện lên trình duyệt vì đã chạy xong
                }

                // Chỉ lưu vết cleanup nếu element không nằm trong .content-wrapper (vì các phần tử trong .content-wrapper tự động giải phóng bởi GC khi thay đổi innerHTML)
                const isInsideWrapper = (this instanceof Element) && document.querySelector(".content-wrapper")?.contains(this);
                if (!isInsideWrapper) {
                    self.pageListeners.push({ target: this, type, listener, options });
                }
            }
            originalAddEventListener.call(this, type, listener, options);
        };

        // Hook EventTarget.prototype.removeEventListener
        const originalRemoveEventListener = EventTarget.prototype.removeEventListener;
        EventTarget.prototype.removeEventListener = function(type, listener, options) {
            self.pageListeners = self.pageListeners.filter(item => 
                !(item.target === this && item.type === type && item.listener === listener)
            );
            originalRemoveEventListener.call(this, type, listener, options);
        };

        // Hook setInterval
        const originalSetInterval = window.setInterval;
        window.setInterval = function(callback, delay, ...args) {
            const id = originalSetInterval.call(this, callback, delay, ...args);
            if (self.isExecutingScripts) {
                self.pageIntervals.push(id);
            }
            return id;
        };

        const originalClearInterval = window.clearInterval;
        window.clearInterval = function(id) {
            self.pageIntervals = self.pageIntervals.filter(x => x !== id);
            originalClearInterval.call(this, id);
        };

        // Hook setTimeout
        const originalSetTimeout = window.setTimeout;
        window.setTimeout = function(callback, delay, ...args) {
            const id = originalSetTimeout.call(this, callback, delay, ...args);
            if (self.isExecutingScripts) {
                self.pageTimeouts.push(id);
            }
            return id;
        };

        const originalClearTimeout = window.clearTimeout;
        window.clearTimeout = function(id) {
            self.pageTimeouts = self.pageTimeouts.filter(x => x !== id);
            originalClearTimeout.call(this, id);
        };

        // Hook EventSource (SSE)
        const originalEventSource = window.EventSource;
        window.EventSource = function(url, configuration) {
            const instance = new originalEventSource(url, configuration);
            if (self.isExecutingScripts) {
                self.pageEventSources.push(instance);
            }
            return instance;
        };
        window.EventSource.prototype = originalEventSource.prototype;
    }

    initProgressBar() {
        this.progressBar = document.createElement("div");
        this.progressBar.className = "pjax-progress-bar";
        document.body.appendChild(this.progressBar);
    }

    showProgressBar() {
        this.progressBar.style.transition = "none";
        this.progressBar.style.width = "0%";
        this.progressBar.style.opacity = "1";
        
        // Force reflow
        this.progressBar.offsetHeight;
        
        this.progressBar.style.transition = "width 0.4s cubic-bezier(0.08, 0.82, 0.17, 1)";
        this.progressBar.style.width = "40%";
        
        this.progressTimer = setTimeout(() => {
            this.progressBar.style.width = "80%";
        }, 400);
    }

    hideProgressBar() {
        if (this.progressTimer) clearTimeout(this.progressTimer);
        this.progressBar.style.transition = "width 0.2s ease";
        this.progressBar.style.width = "100%";
        
        setTimeout(() => {
            this.progressBar.style.transition = "opacity 0.25s ease";
            this.progressBar.style.opacity = "0";
        }, 150);
    }

    cleanupPageResources() {
        // 1. Dọn dẹp intervals
        this.pageIntervals.forEach(id => clearInterval(id));
        this.pageIntervals = [];

        // 2. Dọn dẹp timeouts
        this.pageTimeouts.forEach(id => clearTimeout(id));
        this.pageTimeouts = [];

        // 3. Đóng kết nối EventSource (SSE)
        this.pageEventSources.forEach(es => {
            try {
                es.close();
            } catch (e) {}
        });
        this.pageEventSources = [];

        // 4. Gỡ bỏ event listeners của trang cũ trên đối tượng toàn cục
        this.pageListeners.forEach(item => {
            try {
                item.target.removeEventListener(item.type, item.listener, item.options);
            } catch (e) {}
        });
        this.pageListeners = [];

        // 5. Tạm dừng (Pause) các phần tử audio/video đang phát để tránh phát tiếng ngầm
        document.querySelectorAll("audio, video").forEach(media => {
            try {
                media.pause();
            } catch (e) {}
        });
    }

    bindEvents() {
        // Bắt click trên toàn bộ liên kết
        document.addEventListener("click", e => {
            const anchor = e.target.closest("a");
            if (!anchor) return;
            
            // Chỉ xử lý click chuột trái thông thường không giữ Ctrl/Shift/Meta/Alt
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            
            const href = anchor.getAttribute("href");
            if (!href) return;
            
            // Bỏ qua các link ngoài origin
            if (href.startsWith("http") && !href.startsWith(window.location.origin)) return;
            
            // Bỏ qua các link đăng nhập, đăng xuất, đăng ký
            if (href.includes("/auth/") || href.includes("logout") || href.includes("login") || href.includes("register")) {
                return;
            }
            
            // Bỏ qua target="_blank"
            if (anchor.getAttribute("target") === "_blank") return;
            
            // Bỏ qua hash links hoặc javascript
            if (href.startsWith("#") || href.startsWith("javascript:")) return;
            
            e.preventDefault();
            
            // Cập nhật active class cho sidebar menu ngay lập tức để cho cảm giác phản hồi nhanh (Instant Active State)
            if (anchor.classList.contains("menu-item") && anchor.closest(".app-sidebar")) {
                const menuItems = document.querySelectorAll(".app-sidebar .menu-item");
                menuItems.forEach(item => item.classList.remove("active"));
                anchor.classList.add("active");
            }

            this.navigate(anchor.href);
        });

        // Bắt sự kiện quay lại/tiến tới của trình duyệt (back/forward)
        window.addEventListener("popstate", () => {
            this.navigate(window.location.href, false);
        });
    }

    async navigate(url, pushState = true) {
        this.showProgressBar();
        this.cleanupPageResources();

        try {
            const response = await fetch(url);
            if (!response.ok) {
                window.location.href = url;
                return;
            }

            const htmlText = await response.text();
            
            // Kiểm tra xem trang có bị redirect về auth không (ví dụ hết hạn session)
            const finalUrl = response.url || url;
            if (finalUrl.includes("/auth/") || finalUrl.includes("login")) {
                window.location.href = finalUrl;
                return;
            }

            const parser = new DOMParser();
            const doc = parser.parseFromString(htmlText, "text/html");

            // Thay đổi nội dung của .content-wrapper
            const currentWrapper = document.querySelector(".content-wrapper");
            const newWrapper = doc.querySelector(".content-wrapper");
            
            if (currentWrapper && newWrapper) {
                currentWrapper.innerHTML = newWrapper.innerHTML;
            } else {
                window.location.href = url;
                return;
            }

            // Cập nhật tiêu đề trang
            const newTitle = doc.querySelector("title");
            if (newTitle) {
                document.title = newTitle.textContent;
            }

            // Kích hoạt thực thi scripts trong content mới TRƯỚC KHI cập nhật URL.
            // Lấy tất cả các script inline trong trang mới để thực thi (bao gồm từ block extra_js ở cuối body)
            const inlineScripts = Array.from(doc.body.querySelectorAll("script")).filter(script => !script.hasAttribute("src"));
            await this.executeScripts(inlineScripts);

            // Đẩy URL mới vào lịch sử trình duyệt SAU KHI scripts chạy thành công
            if (pushState) {
                history.pushState({}, "", finalUrl);
            }

            // Cập nhật active class cho sidebar menu
            this.updateSidebarActive(finalUrl);

            // Khởi tạo lại Lucide Icons (chỉ quét trong content-wrapper để tránh giật/vẽ lại icons sidebar)
            if (typeof lucide !== "undefined") {
                lucide.createIcons({
                    root: document.querySelector(".content-wrapper")
                });
            }

            // Cuộn trang lên đầu
            window.scrollTo(0, 0);

        } catch (error) {
            console.error("PJAX navigation error, fallback to page load...", error);
            // Lúc này URL trình duyệt vẫn là URL cũ (chưa gọi pushState), gán window.location.href sẽ reload trang đích thật
            window.location.href = url;
        } finally {
            this.hideProgressBar();
        }
    }

    updateSidebarActive(currentUrl) {
        try {
            const path = new URL(currentUrl).pathname;
            const menuItems = document.querySelectorAll(".app-sidebar .menu-item");
            
            menuItems.forEach(item => {
                const href = item.getAttribute("href");
                if (href === path || href + "/" === path || (href !== "/" && path.length > 1 && href.length > 1 && path.startsWith(href))) {
                    item.classList.add("active");
                } else {
                    item.classList.remove("active");
                }
            });
        } catch (e) {
            console.error("Error updating sidebar active link:", e);
        }
    }

    async executeScripts(scripts) {
        if (scripts.length === 0) return;

        this.isExecutingScripts = true;

        for (const script of scripts) {
            const newScript = document.createElement("script");
            
            // Sao chép các thuộc tính (ví dụ: type, src...)
            Array.from(script.attributes).forEach(attr => {
                newScript.setAttribute(attr.name, attr.value);
            });
            
            // Sao chép nội dung script code
            newScript.textContent = script.textContent;
            
            // Chèn vào body để thực thi đồng bộ
            document.body.appendChild(newScript);
            // Xóa script tag tạm thời vừa chèn
            newScript.remove();
        }

        this.isExecutingScripts = false;
    }
}

// Khởi chạy hệ thống PjaxRouter
document.addEventListener("DOMContentLoaded", () => {
    window.pjaxRouter = new PjaxRouter();
});
