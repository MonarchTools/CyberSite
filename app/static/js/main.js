document.addEventListener("DOMContentLoaded", () => {
    console.log("CyberSite initialized successfully.");

    document.documentElement.classList.add("js-ready");
});

document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-captcha-refresh]");

    if (!button) {
        return;
    }

    const form = button.closest("form");
    const image = form && form.querySelector("[data-captcha-image]");

    if (!image) {
        return;
    }

    const base = image.getAttribute("src").split("?")[0];
    image.src = base + "?t=" + Date.now();

    const input = form.querySelector("input[name='captcha']");

    if (input) {
        input.value = "";
        input.focus();
    }
});
