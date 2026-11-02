// اسلایدر صفحهٔ اصلی: بدون وابستگی، سازگار با CSP (فایل خارجی)
(function () {
    "use strict";

    var root = document.querySelector("[data-slider]");

    if (!root) {
        return;
    }

    var slides = Array.prototype.slice.call(root.querySelectorAll("[data-slide]"));
    var dots = Array.prototype.slice.call(root.querySelectorAll("[data-slider-dot]"));
    var index = 0;
    var timer = null;
    var AUTOPLAY_MS = 6000;

    if (slides.length < 2) {
        return;
    }

    function pauseVideos(except) {
        slides.forEach(function (slide, i) {
            var video = slide.querySelector("video");

            if (video && i !== except && !video.paused) {
                video.pause();
            }
        });
    }

    function show(next) {
        index = (next + slides.length) % slides.length;

        slides.forEach(function (slide, i) {
            var active = i === index;

            slide.classList.toggle("active", active);
            slide.setAttribute("aria-hidden", active ? "false" : "true");
        });

        dots.forEach(function (dot, i) {
            var active = i === index;

            dot.classList.toggle("active", active);

            if (active) {
                dot.setAttribute("aria-current", "true");
            } else {
                dot.removeAttribute("aria-current");
            }
        });

        pauseVideos(index);
    }

    function videoIsPlaying() {
        var video = slides[index].querySelector("video");

        return Boolean(video && !video.paused && !video.ended);
    }

    var hovering = false;
    var reduceMotion = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function stop() {
        if (timer) {
            window.clearInterval(timer);
            timer = null;
        }
    }

    function start() {
        stop();

        if (reduceMotion) {
            return;
        }

        timer = window.setInterval(function () {
            // کاربر در حال تماشا یا تعامل است؛ جلو نمی‌رویم
            if (hovering || document.hidden || videoIsPlaying() ||
                root.contains(document.activeElement)) {
                return;
            }

            show(index + 1);
        }, AUTOPLAY_MS);
    }

    function go(next) {
        show(next);
        start();
    }

    var prev = root.querySelector("[data-slider-prev]");
    var nextButton = root.querySelector("[data-slider-next]");

    if (prev) {
        prev.addEventListener("click", function () { go(index - 1); });
    }

    if (nextButton) {
        nextButton.addEventListener("click", function () { go(index + 1); });
    }

    dots.forEach(function (dot) {
        dot.addEventListener("click", function () {
            go(parseInt(dot.getAttribute("data-slider-dot"), 10) || 0);
        });
    });

    // سایت راست‌به‌چپ است: فلش چپ = بعدی، فلش راست = قبلی
    root.addEventListener("keydown", function (event) {
        if (event.target && event.target.tagName === "VIDEO") {
            return;
        }

        if (event.key === "ArrowLeft") {
            go(index + 1);
        } else if (event.key === "ArrowRight") {
            go(index - 1);
        }
    });

    root.addEventListener("mouseenter", function () { hovering = true; });
    root.addEventListener("mouseleave", function () { hovering = false; });

    var touchX = null;

    root.addEventListener("touchstart", function (event) {
        touchX = event.changedTouches[0].clientX;
    }, { passive: true });

    root.addEventListener("touchend", function (event) {
        if (touchX === null) {
            return;
        }

        var delta = event.changedTouches[0].clientX - touchX;
        touchX = null;

        if (Math.abs(delta) > 50) {
            // کشیدن به چپ در متن راست‌به‌چپ = اسلاید بعدی
            go(delta < 0 ? index + 1 : index - 1);
        }
    }, { passive: true });

    show(0);
    start();
})();
