// Script quản lý Light/Dark mode
(function () {
    const savedTheme = localStorage.getItem("voiceai-theme");
    
    // Nếu có theme đã lưu thì áp dụng, ngược lại dùng theme mặc định hệ thống hoặc mặc định dark
    if (savedTheme) {
        document.documentElement.setAttribute("data-theme", savedTheme);
    } else {
        // Mặc định là Dark mode
        document.documentElement.setAttribute("data-theme", "dark");
    }
})();

document.addEventListener("DOMContentLoaded", () => {
    const themeToggleBtn = document.getElementById("theme-toggle");
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            const currentTheme = document.documentElement.getAttribute("data-theme");
            const newTheme = currentTheme === "light" ? "dark" : "light";
            
            document.documentElement.setAttribute("data-theme", newTheme);
            localStorage.setItem("voiceai-theme", newTheme);
            
            // Cập nhật icon theme nếu có
            updateThemeIcon(newTheme);
        });
        
        // Khởi tạo icon ban đầu
        const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
        updateThemeIcon(currentTheme);
    }
});

function updateThemeIcon(theme) {
    const iconEl = document.querySelector("#theme-toggle i");
    if (iconEl) {
        if (theme === "light") {
            iconEl.className = "lucide-sun";
            iconEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M22 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>`;
        } else {
            iconEl.className = "lucide-moon";
            iconEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-moon"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>`;
        }
    }
}
