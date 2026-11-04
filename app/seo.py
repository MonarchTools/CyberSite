"""کمک‌های سئو: آدرس مطلق، canonical و تصویر پیش‌نمایش لینک."""

from flask import current_app, request, url_for


# اندازهٔ استاندارد تصویر پیش‌نمایش (Open Graph)
OG_WIDTH = 1200
OG_HEIGHT = 630

# پارامترهایی که صفحه را «فیلتر/جست‌وجو» می‌کنند؛ این صفحه‌ها ایندکس نمی‌شوند
FILTER_PARAMS = ("q", "category", "sort", "in_stock")


def base_url():
    """آدرس عمومی سایت بدون اسلش پایانی؛ SITE_URL و در غیاب آن آدرس درخواست."""
    configured = (current_app.config.get("SITE_URL") or "").strip()
    return (configured or request.url_root).rstrip("/")


def absolute_url(path):
    """مسیر داخلی (/...) را به آدرس کامل تبدیل می‌کند."""
    if path.startswith(("http://", "https://")):
        return path

    return f"{base_url()}/{path.lstrip('/')}"


def canonical_url():
    """آدرس اصلی صفحهٔ جاری: بدون پارامترهای جست‌وجو و فیلتر، فقط شمارهٔ صفحه."""
    url = absolute_url(request.path)
    page = request.args.get("page", "")

    if page.isascii() and page.isdigit() and int(page) > 1:
        url += f"?page={int(page)}"

    return url


def has_filters():
    return any(request.args.get(name) for name in FILTER_PARAMS)


def og_image_url(kind, stored_name):
    """آدرس مطلق نسخهٔ JPEG تصویر ذخیره‌شده؛ بدون تصویر، تصویر پیش‌فرض سایت."""
    if not stored_name:
        return absolute_url(url_for("static", filename="og-default.jpg"))

    stem = stored_name.rsplit(".", 1)[0]

    return absolute_url(
        url_for("seo.og_image", kind=kind, name=f"{stem}.jpg")
    )


def init_seo(app):
    @app.context_processor
    def inject_seo():
        return {
            "seo_canonical": canonical_url,
            "seo_url": absolute_url,
            "seo_og_image": og_image_url,
            "seo_has_filters": has_filters,
        }
