import re

from app.extensions import db
from app.utils import utcnow_naive


_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\s]+\)")
_MARKS = re.compile(r"[#*`>]|^[-]\s+", re.MULTILINE)


# جدول واسط پست و برچسب (چند به چند)
post_tags = db.Table(
    "post_tags",
    db.Column(
        "post_id", db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    ),
    db.Column(
        "tag_id", db.Integer,
        db.ForeignKey("blog_tags.id", ondelete="CASCADE"), primary_key=True
    ),
)


class BlogCategory(db.Model):
    """دستهٔ وبلاگ (جدا از دستهٔ محصولات فروشگاه)."""

    __tablename__ = "blog_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)


class BlogTag(db.Model):
    __tablename__ = "blog_tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)


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

    # تعداد بازدید بازدیدکنندگان (مدیر و ربات‌های پیش‌نمایش لینک شمرده نمی‌شوند)
    view_count = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )

    category_id = db.Column(
        db.Integer,
        db.ForeignKey("blog_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    category = db.relationship("BlogCategory", lazy="joined")

    tags = db.relationship(
        "BlogTag",
        secondary=post_tags,
        order_by="BlogTag.name",
        lazy="selectin"
    )

    # عکس‌های داخل متن (آپلودشده برای همین پست)
    body_images = db.relationship(
        "PostImage",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostImage.id",
        lazy="selectin"
    )

    @property
    def summary(self):
        """خلاصهٔ متنی برای کارت و meta description (فقط متن ساده)."""
        if self.excerpt:
            return self.excerpt

        text = _LINK.sub(r"\1", self.body or "")
        text = _MARKS.sub("", text)
        text = " ".join(text.split())

        return text if len(text) <= 160 else text[:157].rstrip() + "…"


class PostImage(db.Model):
    __tablename__ = "post_images"

    id = db.Column(db.Integer, primary_key=True)

    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # نام تولیدشدهٔ برنامه (۳۲ رقم hex + .webp)
    filename = db.Column(db.String(64), nullable=False)

    post = db.relationship("Post", back_populates="body_images")
