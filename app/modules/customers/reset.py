"""توکن بازیابی رمز عبور: امضاشده، زمان‌دار و یک‌بارمصرف.

- توکن چیزی در دیتابیس ذخیره نمی‌کند؛ با SECRET_KEY امضا می‌شود.
- «اثر انگشت» هش رمز فعلی داخل توکن است؛ پس بعد از تغییر رمز، همهٔ توکن‌های قبلی
  بی‌اثر می‌شوند (یک‌بارمصرف).
"""

import hashlib
import hmac

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.extensions import db
from app.modules.customers.models import Customer


SALT = "customer-password-reset"


def reset_minutes():
    return int(current_app.config.get("PASSWORD_RESET_MINUTES", 60))


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def _fingerprint(customer):
    key = str(current_app.config["SECRET_KEY"]).encode()

    return hmac.new(
        key, customer.password_hash.encode(), hashlib.sha256
    ).hexdigest()[:20]


def make_token(customer):
    return _serializer().dumps({"id": customer.id, "fp": _fingerprint(customer)})


def read_token(token):
    """مشتریِ صاحب توکن یا None (نامعتبر، منقضی، استفاده‌شده یا مشتری غیرفعال)."""
    try:
        data = _serializer().loads(token, max_age=reset_minutes() * 60)
    except BadSignature:       # شامل SignatureExpired
        return None

    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        return None

    customer = db.session.get(Customer, data["id"])

    if customer is None or not customer.is_active:
        return None

    if not hmac.compare_digest(str(data.get("fp", "")), _fingerprint(customer)):
        return None

    return customer
