from datetime import datetime, timezone

from app.extensions import db


def is_safe_link(url):
    """فقط مسیر داخلی (/…) یا آدرس https؛ نه javascript:، data: یا // خارجی."""
    url = (url or "").strip()

    if not url or len(url) > 300 or any(c in url for c in ' \t\r\n\\<>"\''):
        return False

    if url.startswith("/"):
        return not url.startswith("//")

    return url.lower().startswith("https://") and len(url) > len("https://")


class HomeSlide(db.Model):
    __tablename__ = "home_slides"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    caption = db.Column(db.String(200), nullable=True)
    link_url = db.Column(db.String(300), nullable=True)

    # "image" یا "video"
    media_type = db.Column(db.String(10), nullable=False, default="image")
    # نام تولیدشدهٔ برنامه (۳۲ رقم hex + .webp/.mp4/.webm)
    filename = db.Column(db.String(64), nullable=False)

    position = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    @property
    def is_video(self):
        return self.media_type == "video"

    @property
    def safe_link(self):
        """لینک فقط در صورت امن‌بودن برمی‌گردد (دفاع دوم هنگام نمایش)."""
        return self.link_url if is_safe_link(self.link_url) else None

    @property
    def link_is_external(self):
        return bool(self.safe_link) and not self.safe_link.startswith("/")
