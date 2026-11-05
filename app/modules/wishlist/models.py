from app.extensions import db
from app.utils import utcnow_naive


class WishlistItem(db.Model):
    """محصولی که مشتری به علاقه‌مندی‌هایش اضافه کرده است."""

    __tablename__ = "wishlist_items"
    __table_args__ = (
        db.UniqueConstraint("customer_id", "product_id", name="uq_wishlist_pair"),
    )

    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id"), nullable=False, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
