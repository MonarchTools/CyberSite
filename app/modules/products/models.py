
from datetime import datetime, timezone

from app.extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    products = db.relationship(
        "Product",
        back_populates="category",
        lazy=True
    )


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # قیمت به ریال، عدد صحیح (بدون اعشار)
    price = db.Column(db.BigInteger, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_filename = db.Column(db.String(255), nullable=True)

    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    category = db.relationship(
        "Category",
        back_populates="products"
    )

    # تصاویر بیشتر (گالری)؛ تصویر اصلی همان image_filename است
    gallery = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position, ProductImage.id",
        lazy="selectin"
    )

    @property
    def image_names(self):
        """همهٔ تصاویر محصول به ترتیب نمایش (اصلی اول)."""
        names = [self.image_filename] if self.image_filename else []
        return names + [image.filename for image in self.gallery]


class ProductImage(db.Model):
    __tablename__ = "product_images"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # نام تولیدشدهٔ برنامه (۳۲ رقم hex + .webp)
    filename = db.Column(db.String(64), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship("Product", back_populates="gallery")
