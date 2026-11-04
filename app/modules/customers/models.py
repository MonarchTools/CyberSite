from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import utcnow_naive


class Customer(db.Model):
    """حساب مشتری (جدا از مدیر). ورود با ایمیل و رمز عبور."""

    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)

    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default="1"
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    orders = db.relationship(
        "Order",
        back_populates="customer",
        order_by="Order.created_at.desc()",
        lazy="select"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
