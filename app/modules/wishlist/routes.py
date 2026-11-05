from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, url_for
)
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.modules.customers.auth import (
    current_customer, customer_required, safe_next
)
from app.modules.products.models import Product
from app.modules.wishlist.models import WishlistItem


wishlist_bp = Blueprint("wishlist", __name__, url_prefix="/account/wishlist")

MAX_ITEMS = 200


def wishlist_ids():
    """شناسهٔ محصولات علاقه‌مندی مشتری واردشده (برای نمایش قلب‌ها)؛ هر درخواست یک‌بار."""
    if hasattr(g, "_wishlist_ids"):
        return g._wishlist_ids

    customer = current_customer()

    if customer is None:
        g._wishlist_ids = frozenset()
    else:
        g._wishlist_ids = frozenset(
            pid for (pid,) in db.session.query(WishlistItem.product_id)
            .filter(WishlistItem.customer_id == customer.id)
        )

    return g._wishlist_ids


@wishlist_bp.route("/")
@customer_required
def index():
    customer = current_customer()

    rows = (
        db.session.query(WishlistItem, Product)
        .join(Product, Product.id == WishlistItem.product_id)
        .filter(WishlistItem.customer_id == customer.id)
        .order_by(WishlistItem.created_at.desc())
        .all()
    )

    return render_template(
        "wishlist/index.html",
        products=[product for _, product in rows],
    )


@wishlist_bp.route("/toggle/<int:product_id>", methods=["POST"])
def toggle(product_id):
    product = db.session.get(Product, product_id)

    if product is None:
        abort(404)

    fallback = url_for("products.detail", product_id=product.id)
    back = safe_next(request.form.get("next", ""), fallback)

    customer = current_customer()

    if customer is None:
        flash("برای افزودن به علاقه‌مندی‌ها ابتدا وارد حساب کاربری شوید.", "warning")
        return redirect(url_for("customers.login", next=back))

    existing = WishlistItem.query.filter_by(
        customer_id=customer.id, product_id=product.id
    ).first()

    if existing is not None:
        db.session.delete(existing)
        db.session.commit()
        flash("از علاقه‌مندی‌ها برداشته شد.", "success")
        return redirect(back)

    total = WishlistItem.query.filter_by(customer_id=customer.id).count()

    if total >= MAX_ITEMS:
        flash(f"حداکثر {MAX_ITEMS} محصول می‌تواند در علاقه‌مندی‌ها باشد.", "warning")
        return redirect(back)

    try:
        db.session.add(WishlistItem(customer_id=customer.id, product_id=product.id))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()   # دو کلیک هم‌زمان؛ همان‌طور که بود می‌ماند

    flash("به علاقه‌مندی‌ها اضافه شد.", "success")
    return redirect(back)
