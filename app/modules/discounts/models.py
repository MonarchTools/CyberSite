from app.extensions import db
from app.utils import utcnow_naive


class DiscountKind:
    PERCENT = "percent"
    FIXED = "fixed"

    ALL = (PERCENT, FIXED)

    LABELS = {
        PERCENT: "درصدی",
        FIXED: "مبلغ ثابت",
    }


class DiscountCode(db.Model):
    """کد تخفیف؛ مدیر می‌سازد و مشتری در سبد خرید وارد می‌کند."""

    __tablename__ = "discount_codes"

    id = db.Column(db.Integer, primary_key=True)

    # همیشه با حروف بزرگ انگلیسی ذخیره می‌شود
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)

    kind = db.Column(db.String(10), nullable=False, default=DiscountKind.PERCENT)
    # درصد (۱ تا ۱۰۰) یا مبلغ ثابت به ریال
    value = db.Column(db.BigInteger, nullable=False)

    # حداقل مبلغ سبد برای اعمال کد (ریال؛ 0 = بدون حداقل)
    min_order_rial = db.Column(
        db.BigInteger, nullable=False, default=0, server_default="0"
    )
    # سقف مبلغ تخفیف برای کدهای درصدی (خالی = بدون سقف)
    max_discount_rial = db.Column(db.BigInteger, nullable=True)

    # کل دفعات قابل استفاده (خالی = نامحدود) و دفعات مصرف‌شده/رزرو‌شده
    max_uses = db.Column(db.Integer, nullable=True)
    used_count = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    once_per_customer = db.Column(
        db.Boolean, nullable=False, default=True, server_default="1"
    )

    # پایان اعتبار (UTC، تا آخر همان روز)؛ خالی = بدون انقضا
    expires_at = db.Column(db.DateTime, nullable=True)

    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default="1"
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    @property
    def kind_label(self):
        return DiscountKind.LABELS.get(self.kind, self.kind)

    @property
    def value_label(self):
        if self.kind == DiscountKind.PERCENT:
            return f"{int(self.value)}٪"

        return f"{int(self.value):,} ریال"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < utcnow_naive())

    @property
    def is_used_up(self):
        return self.max_uses is not None and self.used_count >= self.max_uses
