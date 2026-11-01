import os


class Config:

    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "change-this-secret-key"
    )

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
