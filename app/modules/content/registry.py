"""فهرست متن‌های قابل‌ویرایش.

فقط کلیدهای این فهرست پذیرفته می‌شوند؛ مقدارها همیشه متن ساده‌اند و در
قالب‌ها escape می‌شوند، پس هیچ HTML یا اسکریپتی از اینجا وارد صفحه نمی‌شود.
"""

import re

TEXT, MULTILINE, URL, EMAIL = "text", "multiline", "url", "email"

_EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _field(key, label, default, kind=TEXT, max_length=80):
    return {
        "key": key, "label": label, "default": default,
        "kind": kind, "max": max_length,
    }


SECTIONS = (
    ("صفحهٔ اصلی", (
        _field("home_badge", "برچسب بالای عنوان", "PERSONAL CYBER PLATFORM", max_length=40),
        _field("home_title_prefix", "عنوان — بخش عادی", "دنیای من در", max_length=40),
        _field("home_title_accent", "عنوان — بخش رنگی", "فضای سایبری", max_length=30),
        _field("home_description", "توضیح زیر عنوان",
               "به وب‌سایت شخصی من خوش آمدید. اینجا دنیایی از برنامه‌نویسی، "
               "تکنولوژی، امنیت سایبری و پروژه‌های من است.",
               MULTILINE, 300),
        _field("home_btn_store", "دکمهٔ اول", "مشاهده فروشگاه", max_length=30),
        _field("home_btn_blog", "دکمهٔ دوم", "مطالعه وبلاگ", max_length=30),
        _field("feature1_title", "کارت ۱ — عنوان", "برنامه‌نویسی", max_length=40),
        _field("feature1_text", "کارت ۱ — متن", "پروژه‌ها و تجربیات برنامه‌نویسی", max_length=100),
        _field("feature2_title", "کارت ۲ — عنوان", "امنیت سایبری", max_length=40),
        _field("feature2_text", "کارت ۲ — متن", "دنیای امنیت و تکنولوژی", max_length=100),
        _field("feature3_title", "کارت ۳ — عنوان", "فروشگاه", max_length=40),
        _field("feature3_text", "کارت ۳ — متن", "محصولات و خدمات دیجیتال", max_length=100),
        _field("slider_heading", "عنوان اسلایدر", "از پروژه‌ها", max_length=40),
    )),
    ("صفحهٔ درباره من", (
        _field("about_title", "عنوان صفحه", "درباره من", max_length=40),
        _field("about_intro", "متن معرفی",
               "سلام! اینجا فضای شخصی من است؛ جایی برای برنامه‌نویسی، "
               "تکنولوژی، امنیت سایبری و پروژه‌هایی که می‌سازم.",
               MULTILINE, 700),
        _field("about1_title", "کارت ۱ — عنوان", "برنامه‌نویسی", max_length=40),
        _field("about1_text", "کارت ۱ — متن", "ساخت وب‌سایت و ابزار با پایتون و Flask", max_length=100),
        _field("about2_title", "کارت ۲ — عنوان", "امنیت سایبری", max_length=40),
        _field("about2_text", "کارت ۲ — متن", "امن‌سازی و یادگیری مداوم", max_length=100),
        _field("about3_title", "کارت ۳ — عنوان", "پروژه‌ها", max_length=40),
        _field("about3_text", "کارت ۳ — متن", "از ایده تا محصول واقعی", max_length=100),
    )),
    ("راه‌های ارتباطی", (
        # پیش‌فرض این‌ها از تنظیمات (.env) خوانده می‌شود
        _field("instagram_url", "لینک اینستاگرام (https)",
               lambda c: c.get("SOCIAL_INSTAGRAM_URL", ""), URL, 200),
        _field("telegram_url", "لینک تلگرام (https)",
               lambda c: c.get("SOCIAL_TELEGRAM_URL", ""), URL, 200),
        _field("public_email", "ایمیل نمایشی",
               lambda c: c.get("PUBLIC_EMAIL", ""), EMAIL, 120),
    )),
)

FIELDS = {f["key"]: f for _, fields in SECTIONS for f in fields}


def default_for(field, config):
    default = field["default"]
    return default(config) if callable(default) else default


def https_only(url):
    url = (url or "").strip()
    return url if url.lower().startswith("https://") and len(url) > 8 \
        and not re.search(r"[\s<>\"'\\]", url) else ""


def clean_value(field, raw):
    """مقدار ورودی را پاک و اعتبارسنجی می‌کند: (مقدار، پیام خطا یا None)."""
    value = _CONTROL.sub("", str(raw or "").replace("\r\n", "\n").replace("\r", "\n"))

    if field["kind"] == MULTILINE:
        value = "\n".join(line.strip() for line in value.split("\n")).strip()
    else:
        value = " ".join(value.split())

    if len(value) > field["max"]:
        return value, f"حداکثر {field['max']} کاراکتر مجاز است."

    if value and field["kind"] == URL and not https_only(value):
        return value, "آدرس باید با https:// شروع شود."

    if value and field["kind"] == EMAIL and not _EMAIL.match(value):
        return value, "ایمیل معتبر نیست."

    return value, None
