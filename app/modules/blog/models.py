import re

from app.extensions import db
from app.utils import utcnow_naive


_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\s]+\)")
_MARKS = re.compile(r"[#*`>]|^[-]\s+", re.MULTILINE)


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    excerpt = db.Column(db.String(300), nullable=True)
    # نام فایل تصویر شاخص (تولیدشده توسط برنامه: ۳۲ رقم hex + .webp)
    cover_image = db.Column(db.String(64), nullable=True)
    body = db.Column(db.Text, nullable=False)

    is_published = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow_naive
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive
    )
    published_at = db.Column(db.DateTime, nullable=True, index=True)

    @property
    def summary(self):
        """خلاصهٔ متنی برای کارت و meta description (فقط متن ساده)."""
        if self.excerpt:
            return self.excerpt

        text = _LINK.sub(r"\1", self.body or "")
        text = _MARKS.sub("", text)
        text = " ".join(text.split())

        return text if len(text) <= 160 else text[:157].rstrip() + "…"
