// پوسته را پیش از رسم صفحه تنظیم می‌کند تا هنگام بارگذاری پرش رنگ دیده نشود.
// پیش‌فرض تیره است؛ انتخاب کاربر در مرورگر نگه‌داری می‌شود.
(function () {
    var theme = "dark";

    try {
        var saved = window.localStorage.getItem("theme");

        if (saved === "light" || saved === "dark") {
            theme = saved;
        }
    } catch (error) {
        // حافظهٔ مرورگر در دسترس نیست؛ پوسته پیش‌فرض می‌ماند
    }

    document.documentElement.setAttribute("data-theme", theme);
})();
