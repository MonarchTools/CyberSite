"""تنظیمات امنیتی سراسری: کلید نشست، هدرها، پروکسی."""

import secrets
from datetime import timedelta

from flask import request
from werkzeug.middleware.proxy_fix import ProxyFix


MIN_KEY_LENGTH = 32

WEAK_KEYS = {
    "",
    "change-this-secret-key",
    "your-secret-key-here",
    "secret",
    "changeme",
    "change-me",
}

# مسیرهایی که اطلاعات شخصی یا مدیریتی نشان می‌دهند و نباید کش شوند
PRIVATE_PREFIXES = (
    "/admin",
    "/shop/manage",
    "/shop/order",
    "/shop/checkout",
    "/shop/cart",
    "/shop/payment",
    "/shop/mock-pay",
    "/contact/manage",
    "/products/manage",
    "/products/create",
    "/products/edit",
)

# بدون inline script/style؛ فقط منابع خود سایت
CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "img-src 'self' data:",
    "style-src 'self'",
    "script-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
))


def ensure_secret_key(app):
    """در تولید، کلید ضعیف یا نبودن SECRET_KEY باعث توقف برنامه می‌شود."""
    key = app.config.get("SECRET_KEY") or ""
    placeholder = key.strip().lower() in WEAK_KEYS

    if not placeholder and len(key) >= MIN_KEY_LENGTH:
        return

    if app.testing or app.debug:
        if placeholder:
            # فقط برای توسعه: کلید تصادفی؛ با هر اجرا نشست‌ها پاک می‌شوند
            app.config["SECRET_KEY"] = secrets.token_hex(32)
            app.logger.warning(
                "SECRET_KEY تنظیم نشده؛ برای توسعه از کلید موقت استفاده شد."
            )
        return

    raise RuntimeError(
        "SECRET_KEY تنظیم نشده یا ضعیف است (حداقل 32 کاراکتر). "
        "یک کلید بسازید و در .env بگذارید:\n"
        "  python -c \"import secrets; print(secrets.token_hex(32))\""
    )


def init_security(app):
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=app.config.get("ADMIN_SESSION_HOURS", 8)
    )

    proxies = int(app.config.get("TRUSTED_PROXY_COUNT", 0) or 0)

    if proxies > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxies,
            x_proto=proxies,
            x_host=proxies,
        )

    @app.after_request
    def set_security_headers(response):
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        headers.setdefault(
            "Content-Security-Policy", CONTENT_SECURITY_POLICY
        )

        if app.config.get("SESSION_COOKIE_SECURE"):
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        if request.path.startswith(PRIVATE_PREFIXES):
            headers["Cache-Control"] = "no-store, max-age=0"
            headers["Pragma"] = "no-cache"

        return response
