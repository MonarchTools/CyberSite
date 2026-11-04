// صفحهٔ بارگذاری را وقتی کنار می‌زند که صفحه ساخته شده و فونت آماده باشد.
(function () {
    var loader = document.getElementById("page-loader");

    if (!loader) {
        return;
    }

    var finished = false;

    function finish() {
        if (finished) {
            return;
        }

        finished = true;
        loader.classList.add("is-done");
    }

    // استایل‌ها در head هستند و قبل از رسم صفحه اعمال می‌شوند؛ پس لازم نیست منتظر
    // دانلود همهٔ تصویرها (رویداد load) بمانیم. فقط منتظر ساخته شدن صفحه و فونت می‌مانیم.
    function whenParsed(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback, { once: true });
        } else {
            callback();
        }
    }

    whenParsed(function () {
        // یک فریم صبر می‌کنیم تا مرورگر دانلود فونت لازم را شروع کند
        window.requestAnimationFrame(function () {
            if (document.fonts && document.fonts.ready) {
                document.fonts.ready.then(finish, finish);
            } else {
                finish();
            }
        });
    });

    // اگر منبعی گیر کرد، صفحه برای همیشه پشت لودینگ نماند
    window.setTimeout(finish, 3000);

    // برگشت با دکمهٔ Back از کش مرورگر: لودینگ نباید دوباره بماند
    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            finish();
        }
    });
})();
