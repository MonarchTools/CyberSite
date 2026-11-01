# CyberSite

ساختار اولیه پروژه با Flask و الگوی Application Factory و Blueprintها.

## اجرا

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # در ویندوز: copy .env.example .env
python create_admin.py      # ساخت حساب مدیر
python run.py
```

سپس آدرس `http://127.0.0.1:5000` را باز کنید.

تنظیمات محرمانه را در فایل `.env` قرار دهید و آن را در Git منتشر نکنید.

## فروشگاه

- لیست محصولات: `/products/` (جستجو، فیلتر دسته، مرتب‌سازی، فقط موجود، صفحه‌بندی)
- جزئیات محصول: `/products/<id>`
- سبد خرید و ثبت سفارش: `/shop/cart`
- مدیریت محصولات: `/products/manage` — مدیریت سفارش‌ها: `/shop/manage/orders` (نیاز به ورود)

قیمت‌ها به **ریال** و به صورت عدد صحیح ذخیره می‌شوند.

### پرداخت

در `.env` مقدار `ZARINPAL_MERCHANT_ID` را بگذارید. برای آزمایش بدون پرداخت واقعی
`PAYMENT_GATEWAY=mock` و `FLASK_DEBUG=1` را تنظیم کنید؛ درگاه آزمایشی در حالت
غیر‌توسعه به‌طور خودکار غیرفعال است.

### به‌روزرسانی از نسخهٔ قبلی دیتابیس

ستون `products.price` از `Numeric(12,2)` به عدد صحیح ریالی تغییر کرده است و
`db.create_all()` ستون‌های موجود را تغییر نمی‌دهد. اگر قبلاً محصول ثبت کرده‌اید،
قبل از اجرا از `instance/cybersite.db` نسخهٔ پشتیبان بگیرید و قیمت‌ها را یک‌بار
بررسی کنید (یا دیتابیس را پاک و دوباره بسازید).

## تست

```bash
pip install pytest
python -m pytest
```
