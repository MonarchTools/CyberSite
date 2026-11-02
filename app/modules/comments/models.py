from app.extensions import db
from app.utils import utcnow_naive


class CommentStatus:
    PENDING = "pending"    # منتظر تأیید مدیر؛ برای عموم دیده نمی‌شود
    APPROVED = "approved"

    ALL = (PENDING, APPROVED)
    LABELS = {PENDING: "در انتظار تأیید", APPROVED: "تأییدشده"}


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)

    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    name = db.Column(db.String(60), nullable=False)
    body = db.Column(db.Text, nullable=False)

    status = db.Column(
        db.String(12),
        nullable=False,
        default=CommentStatus.PENDING,
        index=True
    )

    # هش HMAC آدرس IP؛ خودِ IP ذخیره نمی‌شود
    ip_hash = db.Column(db.String(64), nullable=False, index=True)

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow_naive,
        index=True
    )

    # با حذف پست، نظرهایش هم حذف می‌شود
    post = db.relationship(
        "Post",
        backref=db.backref(
            "comments",
            cascade="all, delete-orphan",
            order_by="Comment.created_at, Comment.id",
            lazy="select"
        )
    )

    @property
    def status_label(self):
        return CommentStatus.LABELS.get(self.status, self.status)
