from app.extensions import db
from app.utils import utcnow_naive


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    subject = db.Column(db.String(150), nullable=True)
    message = db.Column(db.Text, nullable=False)

    # HMAC از IP فرستنده؛ فقط برای محدودیت تعداد پیام، نه شناسایی فرد
    ip_hash = db.Column(db.String(64), nullable=False, index=True)

    is_read = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow_naive,
        index=True
    )
