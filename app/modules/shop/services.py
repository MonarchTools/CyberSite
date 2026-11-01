"""منطق سبد خرید، رزرو موجودی و نهایی‌سازی پرداخت."""

from dataclasses import dataclass
from datetime import timedelta

from flask import current_app, session
from sqlalchemy import update

from app.notifications import notify_order_paid
from app.extensions import db
from app.modules.products.models import Product
from app.modules.shop.gateways import GatewayError
from app.modules.shop.models import Order, OrderItem, OrderStatus
from app.utils import utcnow_naive


CART_KEY = "cart"
PENDING_ORDER_KEY = "pending_order"


# ---------------------------------------------------------------- سبد خرید

def _max_quantity():
    return current_app.config.get("MAX_CART_ITEM_QUANTITY", 20)


def _read_cart():
    raw = session.get(CART_KEY)
    cart = {}

    if not isinstance(raw, dict):
        return cart

    for key, value in raw.items():
        try:
            product_id = int(key)
            quantity = int(value)
        except (TypeError, ValueError):
            continue

        if quantity >= 1:
            cart[product_id] = min(quantity, _max_quantity())

    return cart


def _write_cart(cart):
    session[CART_KEY] = {str(pid): qty for pid, qty in cart.items()}


def cart_count():
    return sum(_read_cart().values())


def clear_cart():
    session.pop(CART_KEY, None)


@dataclass
class CartLine:
    product: Product
    quantity: int
    issue: str = ""

    @property
    def unit_price(self):
        return int(self.product.price)

    @property
    def line_total(self):
        return self.unit_price * self.quantity


def get_cart_lines():
    """(سطرها، جمع کل). محصولات حذف‌شده از سبد پاک می‌شوند."""
    cart = _read_cart()

    if not cart:
        return [], 0

    products = {
        product.id: product
        for product in Product.query.filter(Product.id.in_(list(cart))).all()
    }

    lines = []
    cleaned = {}

    for product_id, quantity in cart.items():
        product = products.get(product_id)

        if product is None:
            continue

        cleaned[product_id] = quantity
        issue = ""

        if product.stock <= 0:
            issue = "ناموجود"
        elif quantity > product.stock:
            issue = f"فقط {product.stock} عدد موجود است"

        lines.append(CartLine(product, quantity, issue))

    if cleaned != cart:
        _write_cart(cleaned)

    return lines, sum(line.line_total for line in lines)


def add_to_cart(product, quantity):
    """(موفق؟، پیام)."""
    if product.stock <= 0:
        return False, "این محصول ناموجود است."

    cart = _read_cart()
    limit = min(product.stock, _max_quantity())
    new_quantity = min(cart.get(product.id, 0) + max(quantity, 1), limit)

    cart[product.id] = new_quantity
    _write_cart(cart)

    if new_quantity == limit:
        return True, f"به سبد اضافه شد (حداکثر تعداد مجاز: {limit})."

    return True, "به سبد خرید اضافه شد."


def set_cart_quantity(product, quantity):
    cart = _read_cart()

    if quantity <= 0:
        cart.pop(product.id, None)
    else:
        cart[product.id] = min(quantity, _max_quantity())

    _write_cart(cart)


def remove_from_cart(product_id):
    cart = _read_cart()
    cart.pop(product_id, None)
    _write_cart(cart)


# ------------------------------------------------------------ موجودی سفارش

def reserve_stock(order):
    """موجودی اقلام را کم می‌کند. در صورت کمبود False برمی‌گرداند.

    تغییرات داخل تراکنش فعلی‌اند؛ هنگام False فراخواننده باید rollback کند.
    """
    for item in order.items:
        if item.product_id is None:
            return False

        result = db.session.execute(
            update(Product)
            .where(
                Product.id == item.product_id,
                Product.stock >= item.quantity,
            )
            .values(stock=Product.stock - item.quantity)
        )

        if result.rowcount != 1:
            return False

    return True


def release_stock(order):
    for item in order.items:
        if item.product_id is None:
            continue

        db.session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(stock=Product.stock + item.quantity)
        )


def _transition(order, from_status, to_status, **fields):
    """تغییر وضعیت اتمیک؛ فقط یک درخواست برنده می‌شود."""
    result = db.session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == from_status)
        .values(status=to_status, **fields)
    )
    return result.rowcount == 1


def expire_stale_orders():
    """سفارش‌های پرداخت‌نشدهٔ قدیمی را منقضی و موجودی را آزاد می‌کند."""
    minutes = current_app.config.get("ORDER_RESERVATION_MINUTES", 60)
    cutoff = utcnow_naive() - timedelta(minutes=minutes)

    stale = Order.query.filter(
        Order.status == OrderStatus.PENDING,
        Order.created_at < cutoff,
    ).all()

    for order in stale:
        if _transition(order, OrderStatus.PENDING, OrderStatus.EXPIRED):
            release_stock(order)

    db.session.commit()


def cancel_session_pending_order():
    """سفارش پرداخت‌نشدهٔ قبلی همین مشتری را آزاد می‌کند تا موجودی دو بار رزرو نشود."""
    code = session.pop(PENDING_ORDER_KEY, None)

    if not code:
        return

    order = Order.query.filter_by(public_code=code).first()

    if order and _transition(order, OrderStatus.PENDING, OrderStatus.EXPIRED):
        release_stock(order)

    db.session.commit()


def create_order(lines, customer):
    """سفارش را با اقلام و رزرو موجودی می‌سازد (commit نمی‌کند). اگر موجودی نبود None."""
    order = Order(
        total_rial=sum(line.line_total for line in lines),
        full_name=customer["full_name"],
        phone=customer["phone"],
        email=customer.get("email") or None,
        note=customer.get("note") or None,
        items=[
            OrderItem(
                product_id=line.product.id,
                title=line.product.title,
                unit_price_rial=line.unit_price,
                quantity=line.quantity,
            )
            for line in lines
        ],
    )

    db.session.add(order)

    if not reserve_stock(order):
        db.session.rollback()
        return None

    return order


def fail_order(order):
    """سفارش پرداخت‌نشده را ناموفق می‌کند و موجودی را آزاد می‌کند."""
    if _transition(order, OrderStatus.PENDING, OrderStatus.FAILED):
        release_stock(order)


# ------------------------------------------------------- نهایی‌سازی پرداخت

def finalize_payment(order, gateway, status_param, *, recheck=False):
    """نتیجهٔ بازگشت از درگاه را تأیید می‌کند. (کلاس پیام، متن پیام) برمی‌گرداند.

    - مبلغ و شناسهٔ پرداخت فقط از دیتابیس می‌آیند.
    - تغییر وضعیت‌ها اتمیک‌اند، پس بازگشت تکراری هیچ‌چیز را دوباره اعمال نمی‌کند.
    - ``recheck=True``: رد شدن پرداخت از سوی درگاه سفارش را ناموفق نمی‌کند
      (ممکن است مشتری هنوز در صفحهٔ درگاه باشد).
    """
    order._just_paid = False

    try:
        return _finalize(order, gateway, status_param, recheck)
    finally:
        db.session.commit()
        db.session.refresh(order)

        # فقط درخواستی که واقعاً وضعیت را به «پرداخت‌شده» برده ایمیل می‌فرستد
        if order._just_paid:
            notify_order_paid(order)


def _finalize(order, gateway, status_param, recheck):
    if order.status == OrderStatus.PAID:
        return "success", "پرداخت این سفارش قبلاً تأیید شده است."

    if order.status == OrderStatus.FAILED:
        return "danger", "پرداخت این سفارش ناموفق بوده است."

    if status_param != "OK":
        fail_order(order)
        return "danger", "پرداخت انجام نشد یا لغو شد."

    if order.status == OrderStatus.EXPIRED:
        # ممکن است بعد از پایان مهلت پرداخت شده باشد؛ موجودی دوباره رزرو می‌شود.
        revived = _transition(
            order, OrderStatus.EXPIRED, OrderStatus.PENDING
        )

        if not revived:
            return "warning", "وضعیت سفارش در حال به‌روزرسانی است."

        if not reserve_stock(order):
            db.session.rollback()
            return (
                "danger",
                "مهلت پرداخت تمام شده و موجودی دیگر کافی نیست. "
                "اگر مبلغی کسر شده، درگاه آن را به حساب شما بازمی‌گرداند.",
            )

    try:
        ref_id = gateway.verify(order)

    except GatewayError as error:
        if error.retryable:
            return (
                "warning",
                "تأیید پرداخت اکنون ممکن نیست؛ چند دقیقهٔ دیگر "
                "دکمهٔ «بررسی مجدد پرداخت» را بزنید.",
            )

        if recheck:
            return "warning", "پرداختی برای این سفارش تأیید نشد."

        fail_order(order)
        return "danger", f"پرداخت تأیید نشد: {error}"

    order._just_paid = _transition(
        order,
        OrderStatus.PENDING,
        OrderStatus.PAID,
        ref_id=ref_id,
        paid_at=utcnow_naive(),
    )

    return "success", "پرداخت با موفقیت انجام شد. سپاس از خرید شما."
