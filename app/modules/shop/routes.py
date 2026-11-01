from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, session, abort, current_app
)
from flask_login import login_required

from app.extensions import db
from app.modules.products.models import Product
from app.modules.shop.forms import CheckoutForm
from app.modules.shop.gateways import GatewayError, get_gateway
from app.modules.shop.models import Order, OrderStatus
from app.modules.shop.services import (
    PENDING_ORDER_KEY,
    add_to_cart,
    cancel_session_pending_order,
    clear_cart,
    create_order,
    expire_stale_orders,
    fail_order,
    finalize_payment,
    get_cart_lines,
    remove_from_cart,
    set_cart_quantity,
)
from app.utils import to_latin_digits


shop_bp = Blueprint(
    "shop",
    __name__,
    url_prefix="/shop"
)


def _int(value, default):
    try:
        return int(to_latin_digits(str(value)).strip())
    except (TypeError, ValueError):
        return default


def _get_product_or_404(product_id):
    product = db.session.get(Product, product_id)

    if product is None:
        abort(404)

    return product


def _get_order_by_code_or_404(code):
    order = Order.query.filter_by(public_code=code).first()

    if order is None:
        abort(404)

    return order


# ---------------------------------------------------------------- سبد خرید

@shop_bp.route("/cart")
def cart():
    lines, total = get_cart_lines()

    return render_template(
        "shop/cart.html",
        lines=lines,
        total=total,
        has_issue=any(line.issue for line in lines),
        min_payment=current_app.config["MIN_PAYMENT_RIAL"]
    )


@shop_bp.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    product = _get_product_or_404(product_id)
    quantity = _int(request.form.get("quantity"), 1)

    ok, message = add_to_cart(product, quantity)
    flash(message, "success" if ok else "danger")

    return redirect(url_for("shop.cart"))


@shop_bp.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    product = _get_product_or_404(product_id)
    set_cart_quantity(product, _int(request.form.get("quantity"), 1))

    return redirect(url_for("shop.cart"))


@shop_bp.route("/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(product_id):
    remove_from_cart(product_id)
    flash("محصول از سبد حذف شد.", "success")

    return redirect(url_for("shop.cart"))


# ------------------------------------------------------------ ثبت و پرداخت

@shop_bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines, total = get_cart_lines()

    if not lines:
        flash("سبد خرید شما خالی است.", "warning")
        return redirect(url_for("shop.cart"))

    if any(line.issue for line in lines):
        flash("ابتدا مشکل اقلام سبد را برطرف کنید.", "warning")
        return redirect(url_for("shop.cart"))

    minimum = current_app.config["MIN_PAYMENT_RIAL"]

    if total < minimum:
        flash(
            f"حداقل مبلغ سفارش {minimum:,} ریال است.",
            "warning"
        )
        return redirect(url_for("shop.cart"))

    form = CheckoutForm()

    if not form.validate_on_submit():
        return render_template(
            "shop/checkout.html",
            form=form,
            lines=lines,
            total=total
        )

    try:
        gateway = get_gateway()
    except GatewayError as error:
        flash(str(error), "danger")
        return render_template(
            "shop/checkout.html",
            form=form,
            lines=lines,
            total=total
        )

    expire_stale_orders()
    cancel_session_pending_order()

    # بعد از آزادسازی موجودی، سبد دوباره بررسی می‌شود
    lines, total = get_cart_lines()

    if not lines or any(line.issue for line in lines):
        flash("موجودی برخی اقلام تغییر کرده است.", "warning")
        return redirect(url_for("shop.cart"))

    order = create_order(
        lines,
        {
            "full_name": form.full_name.data,
            "phone": form.phone.data,
            "email": form.email.data,
            "note": form.note.data,
        }
    )

    if order is None:
        flash("موجودی برخی اقلام تغییر کرده است.", "warning")
        return redirect(url_for("shop.cart"))

    order.gateway = gateway.name
    db.session.commit()

    site_url = (current_app.config.get("SITE_URL") or "").rstrip("/")
    callback_path = url_for("shop.payment_callback")
    callback_url = (
        site_url + callback_path
        if site_url
        else url_for("shop.payment_callback", _external=True)
    )

    try:
        authority = gateway.start(order, callback_url)

    except GatewayError as error:
        fail_order(order)
        db.session.commit()
        current_app.logger.warning("Payment start failed: %s", error)
        flash(f"اتصال به درگاه پرداخت ممکن نشد: {error}", "danger")
        return redirect(url_for("shop.cart"))

    order.authority = authority
    db.session.commit()

    session[PENDING_ORDER_KEY] = order.public_code

    return redirect(gateway.payment_url(authority))


@shop_bp.route("/payment/callback")
def payment_callback():
    authority = request.args.get("Authority", "")[:64]
    status_param = request.args.get("Status", "")

    order = (
        Order.query.filter_by(authority=authority).first()
        if authority
        else None
    )

    if order is None:
        abort(404)

    try:
        gateway = get_gateway()
    except GatewayError as error:
        flash(str(error), "danger")
        return redirect(
            url_for("shop.order_detail", code=order.public_code)
        )

    category, message = finalize_payment(order, gateway, status_param)

    if order.status == OrderStatus.PAID:
        clear_cart()
        session.pop(PENDING_ORDER_KEY, None)

    flash(message, category)

    return redirect(url_for("shop.order_detail", code=order.public_code))


@shop_bp.route("/order/<code>")
def order_detail(code):
    order = _get_order_by_code_or_404(code)

    return render_template(
        "shop/order.html",
        order=order,
        can_recheck=(
            order.status in (OrderStatus.PENDING, OrderStatus.EXPIRED)
            and bool(order.authority)
        )
    )


@shop_bp.route("/order/<code>/recheck", methods=["POST"])
def order_recheck(code):
    order = _get_order_by_code_or_404(code)

    if order.status not in (OrderStatus.PENDING, OrderStatus.EXPIRED) \
            or not order.authority:
        return redirect(url_for("shop.order_detail", code=code))

    try:
        gateway = get_gateway()
    except GatewayError as error:
        flash(str(error), "danger")
        return redirect(url_for("shop.order_detail", code=code))

    category, message = finalize_payment(
        order, gateway, "OK", recheck=True
    )

    if order.status == OrderStatus.PAID:
        clear_cart()
        session.pop(PENDING_ORDER_KEY, None)

    flash(message, category)

    return redirect(url_for("shop.order_detail", code=code))


# ---------------------------------------------------- درگاه آزمایشی (توسعه)

@shop_bp.route("/mock-pay/<authority>", methods=["GET", "POST"])
def mock_pay(authority):
    try:
        gateway = get_gateway()
    except GatewayError:
        abort(404)

    if gateway.name != "mock":
        abort(404)

    order = Order.query.filter_by(authority=authority).first()

    if order is None:
        abort(404)

    if request.method == "POST":
        if request.form.get("result") == "ok":
            gateway.mark_paid(authority)
            status = "OK"
        else:
            status = "NOK"

        return redirect(
            url_for(
                "shop.payment_callback",
                Authority=authority,
                Status=status
            )
        )

    return render_template("shop/mock_pay.html", order=order)


# ----------------------------------------------------------- مدیریت سفارش‌ها

@shop_bp.route("/manage/orders")
@login_required
def manage_orders():
    status = request.args.get("status", "")
    page = max(_int(request.args.get("page"), 1), 1)

    query = Order.query

    if status in OrderStatus.ALL:
        query = query.filter(Order.status == status)
    else:
        status = ""

    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False
    )

    return render_template(
        "shop/admin_orders.html",
        pagination=pagination,
        orders=pagination.items,
        current_status=status,
        statuses=OrderStatus
    )


@shop_bp.route("/manage/orders/<int:order_id>")
@login_required
def manage_order_detail(order_id):
    order = db.session.get(Order, order_id)

    if order is None:
        abort(404)

    return render_template("shop/admin_order_detail.html", order=order)
