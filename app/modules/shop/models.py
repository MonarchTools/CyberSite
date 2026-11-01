import secrets
from datetime import datetime, timezone

from app.extensions import db


class OrderStatus:
    PENDING = "pending"      # ساخته شده، منتظر پرداخت (موجودی رزرو است)
    PAID = "paid"            # پرداخت تأیید شد
    FAILED = "failed"        # پرداخت ناموفق یا لغو شد
    EXPIRED = "expired"      # مهلت پرداخت تمام شد

    ALL = (PENDING, PAID, FAILED, EXPIRED)

    LABELS = {
        PENDING: "در انتظار پرداخت",
        PAID: "پرداخت‌شده",
        FAILED: "ناموفق",
        EXPIRED: "منقضی‌شده",
    }


def _utcnow():
    return datetime.now(timezone.utc)


def _new_public_code():
    return secrets.token_urlsafe(16)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)

    # کد غیرقابل‌حدس برای نمایش رسید به مشتری (بدون نیاز به ورود)
    public_code = db.Column(
        db.String(32),
        unique=True,
        nullable=False,
        index=True,
        default=_new_public_code
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True
    )

    total_rial = db.Column(db.BigInteger, nullable=False)

    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    note = db.Column(db.Text, nullable=True)

    gateway = db.Column(db.String(30), nullable=True)
    authority = db.Column(db.String(64), unique=True, nullable=True, index=True)
    ref_id = db.Column(db.String(64), nullable=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=_utcnow,
        index=True
    )
    paid_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def status_label(self):
        return OrderStatus.LABELS.get(self.status, self.status)


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id"),
        nullable=False,
        index=True
    )

    # اگر محصول بعداً حذف شود، ردیف سفارش با همان عنوان و قیمت می‌ماند
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True
    )

    title = db.Column(db.String(150), nullable=False)
    unit_price_rial = db.Column(db.BigInteger, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")

    @property
    def line_total_rial(self):
        return self.unit_price_rial * self.quantity
