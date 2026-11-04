"""کش بلندمدت فایل‌های استاتیک با نسخه‌بندی خودکار آدرس.

به آدرس هر فایل استاتیک در قالب‌ها ``?v=<زمان تغییر فایل>`` اضافه می‌شود؛ پس مرورگر می‌تواند
فایل را یک سال نگه دارد و هر بار که فایلی تغییر کند، آدرس تازه می‌شود و نسخهٔ جدید را می‌گیرد.
نتیجه: رفرش‌های بعدی بدون درخواست دوباره برای CSS/JS/فونت انجام می‌شود.
"""

from datetime import timedelta
from pathlib import Path

from flask import request


def init_static_cache(app):
    # کلید در تنظیمات پیش‌فرض Flask هست و مقدارش None است؛ پس setdefault اثر ندارد
    if app.config.get("SEND_FILE_MAX_AGE_DEFAULT") is None:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(days=365)

    @app.after_request
    def immutable_static(response):
        # فایل‌های نسخه‌دار هرگز تغییر نمی‌کنند؛ حتی با F5 دوباره از سرور پرسیده نمی‌شوند
        if request.endpoint == "static" and response.status_code == 200 and (
            "v" in request.args or request.path.startswith("/static/fonts/")
        ):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )

        return response

    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint != "static" or "v" in values:
            return

        filename = values.get("filename")

        if not filename:
            return

        try:
            values["v"] = int((Path(app.static_folder) / filename).stat().st_mtime)
        except (OSError, ValueError):
            pass
