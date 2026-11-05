"""منطق کد تخفیف: اعتبارسنجی، محاسبهٔ مبلغ و رزرو دفعات استفاده."""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from flask import current_app, session
from sqlalchemy import or_, update

from app.extensions import db
from app.modules.discounts.models import DiscountCode, DiscountKind
from app.utils import to_latin_digits, utcnow_naive


SESSION_KEY = "discount_code"
CODE_PATTERN = re.compile(r"^[A-Z0-9_-]{3,40}$")

# برای همهٔ دلیل‌های نامعتبر بودن یک پیام می‌دهیم تا وجود کد لو نرود
INVALID_MESSAGE = "کد تخفیف معتبر نیست."


def normalize_code(raw):
    """«  summer-۱۴ » → «SUMMER-14»."""
    return re.sub(r"\s+", "", to_latin_digits(raw or "")).upper()


def end_of_day(day):
    """آخر روزِ تاریخ داده‌شده (برای انقضا)؛ مقدار None می‌ماند."""
    if day is None:
        return None

    return datetime.combine(day, time(23, 59, 59))


@dataclass
class Pricing:
    subtotal: int
    discount: int = 0
    code: DiscountCode = None
    error: str = ""
    dropped: bool = False   # کدی در نشست بود ولی دیگر معتبر نیست

    @property
    def payable(self):
        return self.subtotal - self.discount


def _min_payable():
    return int(current_app.config.get("MIN_PAYMENT_RIAL", 0))


def _customer_already_used(code, customer):
    from app.modules.shop.models import Order, OrderStatus

    return db.session.query(Order.id).filter(
        Order.discount_code_id == code.id,
        Order.customer_id == customer.id,
        Order.status == OrderStatus.PAID,
    ).first() is not None


def compute_amount(code, subtotal):
    """مبلغ تخفیف؛ هیچ‌وقت باعث نمی‌شود مبلغ قابل پرداخت از حداقل درگاه کمتر شود."""
    if code.kind == DiscountKind.PERCENT:
        amount = subtotal * int(code.value) // 100

        if code.max_discount_rial:
            amount = min(amount, int(code.max_discount_rial))
    else:
        amount = int(code.value)

    return max(min(amount, subtotal - _min_payable()), 0)


def evaluate(raw_code, subtotal, customer=None):
    """کد را برای این سبد می‌سنجد. Pricing برمی‌گرداند (با error در صورت رد شدن)."""
    code_text = normalize_code(raw_code)
    result = Pricing(subtotal=subtotal)

    code = (
        DiscountCode.query.filter_by(code=code_text).first()
        if CODE_PATTERN.fullmatch(code_text)
        else None
    )

    if code is None or not code.is_active:
        result.error = INVALID_MESSAGE
        return result

    if code.is_expired:
        result.error = "مهلت استفاده از این کد تمام شده است."
        return result

    if code.is_used_up:
        result.error = "ظرفیت استفاده از این کد تمام شده است."
        return result

    if subtotal < int(code.min_order_rial or 0):
        result.error = (
            f"این کد برای سبدهای حداقل {int(code.min_order_rial):,} ریال است."
        )
        return result

    if code.once_per_customer and customer is not None \
            and _customer_already_used(code, customer):
        result.error = "شما قبلاً از این کد استفاده کرده‌اید."
        return result

    amount = compute_amount(code, subtotal)

    if amount <= 0:
        result.error = "این کد روی این سبد تخفیفی ایجاد نمی‌کند."
        return result

    result.code = code
    result.discount = amount

    return result


def current_pricing(subtotal, customer=None):
    """قیمت سبد با کد ذخیره‌شده در نشست. کد نامعتبر از نشست پاک می‌شود."""
    stored = session.get(SESSION_KEY)

    if not stored:
        return Pricing(subtotal=subtotal)

    result = evaluate(stored, subtotal, customer)

    if result.error:
        session.pop(SESSION_KEY, None)
        result.dropped = True

    return result


def remember(code_text):
    session[SESSION_KEY] = normalize_code(code_text)


def forget():
    session.pop(SESSION_KEY, None)


# ----------------------------------------------- رزرو دفعات استفاده (اتمیک)

def reserve_usage(code_id):
    """یک دفعه از ظرفیت کد را رزرو می‌کند؛ اگر پر یا غیرفعال بود False."""
    result = db.session.execute(
        update(DiscountCode)
        .where(
            DiscountCode.id == code_id,
            DiscountCode.is_active.is_(True),
            or_(
                DiscountCode.max_uses.is_(None),
                DiscountCode.used_count < DiscountCode.max_uses,
            ),
        )
        .values(used_count=DiscountCode.used_count + 1)
    )

    return result.rowcount == 1


def release_usage(code_id):
    db.session.execute(
        update(DiscountCode)
        .where(DiscountCode.id == code_id, DiscountCode.used_count > 0)
        .values(used_count=DiscountCode.used_count - 1)
    )


def reclaim_usage(code_id):
    """سفارش منقضی‌شده‌ای که بعداً پرداخت شد؛ بدون بررسی ظرفیت دوباره شمرده می‌شود."""
    db.session.execute(
        update(DiscountCode)
        .where(DiscountCode.id == code_id)
        .values(used_count=DiscountCode.used_count + 1)
    )
