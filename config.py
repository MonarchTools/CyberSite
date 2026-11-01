import os


def _cookie_secure():
    """کوکی Secure فقط وقتی فعال می‌شود که سایت واقعاً روی HTTPS باشد.

    با ``SESSION_COOKIE_SECURE=1`` یا ``0`` در .env می‌شود دستی تعیین کرد.
    """
    explicit = os.getenv("SESSION_COOKIE_SECURE", "").strip()

    if explicit in ("0", "1"):
        return explicit == "1"

    return os.getenv("SITE_URL", "").strip().lower().startswith("https://")


class Config:

    # بدون مقدار پیش‌فرض: اگر در .env نباشد، خارج از حالت توسعه برنامه اجرا نمی‌شود.
    SECRET_KEY = os.getenv("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///cybersite.db"
    )
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- فروشگاه ---
    PRODUCTS_PER_PAGE = 9
    MAX_CART_ITEM_QUANTITY = 20

    # --- پرداخت ---
    # "zarinpal" (پیش‌فرض) یا "mock" (فقط در حالت توسعه/تست)
    PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "zarinpal")
    ZARINPAL_MERCHANT_ID = os.getenv("ZARINPAL_MERCHANT_ID", "")
    ZARINPAL_SANDBOX = os.getenv("ZARINPAL_SANDBOX", "0") == "1"

    # آدرس عمومی سایت، مثلاً https://example.ir ؛ برای callback درگاه استفاده می‌شود.
    # اگر خالی باشد از آدرس درخواست جاری ساخته می‌شود.
    SITE_URL = os.getenv("SITE_URL", "")

    # حداقل مبلغ قابل پرداخت (ریال) و مدت نگه‌داشتن موجودی سفارش پرداخت‌نشده
    MIN_PAYMENT_RIAL = 10_000
    ORDER_RESERVATION_MINUTES = 60

    # --- امنیت نشست و ورود ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _cookie_secure()
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _cookie_secure()

    # بعد از این مدت بی‌فعالیتی، نشست مدیر منقضی می‌شود
    ADMIN_SESSION_HOURS = 8

    # قفل ورود: بعد از این تعداد تلاش ناموفق، IP به همین مدت قفل می‌شود
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCK_MINUTES = 15

    # تعداد پروکسی‌های معتبر جلوی برنامه (مثلاً 1 برای Nginx).
    # فقط وقتی مقدار بدهید که واقعاً پشت پروکسی هستید؛ وگرنه IP قابل جعل می‌شود.
    TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0") or 0)

    # حداکثر پیام فرم تماس از هر IP در یک ساعت
    CONTACT_MAX_PER_HOUR = 5
