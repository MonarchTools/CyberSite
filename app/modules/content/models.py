from datetime import datetime, timezone

from app.extensions import db


class SiteContent(db.Model):
    """متن ویرایش‌شده توسط مدیر. نبودن ردیف یعنی «متن پیش‌فرض»."""

    __tablename__ = "site_content"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)

    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
