"""آمار فروش و بازدید برای داشبورد مدیر (فقط خواندنی)."""

from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.modules.blog.models import Post
from app.modules.products.models import Product
from app.modules.shop.models import Order, OrderItem, OrderStatus
from app.utils import utcnow_naive


LOCAL_OFFSET = timedelta(hours=3, minutes=30)   # تهران؛ روز فروش به وقت محلی حساب می‌شود
DAYS = 30
MONTHS = 12
LOW_STOCK = 5

# ابعاد نمودار SVG (واحد دلخواه؛ با viewBox مقیاس می‌شود)
CHART_W = 600
CHART_H = 180
CHART_PAD = 22


def local_now():
    return utcnow_naive() + LOCAL_OFFSET


def paid_orders_since(days):
    """[(زمان محلی پرداخت، مبلغ)] سفارش‌های پرداخت‌شدهٔ n روز اخیر."""
    cutoff = utcnow_naive() - timedelta(days=days + 1)

    rows = db.session.query(Order.paid_at, Order.total_rial).filter(
        Order.status == OrderStatus.PAID,
        Order.paid_at.isnot(None),
        Order.paid_at >= cutoff,
    ).all()

    return [(paid + LOCAL_OFFSET, total) for paid, total in rows]


def daily_series(orders, days=DAYS, today=None):
    """[(تاریخ، جمع مبلغ، تعداد)] از قدیم به جدید؛ روزهای بدون فروش صفر."""
    today = (today or local_now()).date()
    totals = {}

    for moment, amount in orders:
        key = moment.date()
        sold, count = totals.get(key, (0, 0))
        totals[key] = (sold + amount, count + 1)

    series = []

    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        sold, count = totals.get(day, (0, 0))
        series.append((day, sold, count))

    return series


def monthly_series(orders, months=MONTHS, today=None):
    """[(سال-ماه، جمع مبلغ، تعداد)] ماه‌های میلادی، از قدیم به جدید."""
    today = (today or local_now()).date()
    year, month = today.year, today.month
    keys = []

    for _ in range(months):
        keys.append((year, month))
        month -= 1

        if month == 0:
            year, month = year - 1, 12

    keys.reverse()
    totals = {key: (0, 0) for key in keys}

    for moment, amount in orders:
        key = (moment.year, moment.month)

        if key in totals:
            sold, count = totals[key]
            totals[key] = (sold + amount, count + 1)

    return [(f"{y}-{m:02d}", *totals[(y, m)]) for y, m in keys]


def bar_chart(series, label_every=5):
    """سری [(برچسب، مقدار, ...)] را به مستطیل‌های SVG تبدیل می‌کند.

    زمان در نمودار فارسی از راست به چپ می‌گذرد؛ تازه‌ترین ستون سمت چپ است.
    """
    if not series:
        return {"width": CHART_W, "height": CHART_H, "bars": []}

    peak = max(item[1] for item in series) or 1
    slot = (CHART_W - 2 * CHART_PAD) / len(series)
    bar_w = max(slot * 0.7, 2)
    plot_h = CHART_H - 2 * CHART_PAD
    bars = []

    for index, item in enumerate(series):
        height = round(plot_h * item[1] / peak, 1) if item[1] else 0
        # ستون قدیمی‌تر سمت راست
        x = CHART_W - CHART_PAD - slot * (index + 1) + (slot - bar_w) / 2

        bars.append({
            "x": round(x, 1),
            "y": round(CHART_H - CHART_PAD - height, 1),
            "w": round(bar_w, 1),
            "h": height,
            "label": (
                item[0].strftime("%m/%d") if hasattr(item[0], "strftime")
                else item[0]
            ),
            "amount": item[1],
            "count": item[2],
            # از تازه‌ترین ستون شروع می‌کنیم تا برچسب‌ها روی هم نیفتند
            "show_label": (len(series) - 1 - index) % label_every == 0,
            "label_x": round(x + bar_w / 2, 1),
        })

    return {"width": CHART_W, "height": CHART_H, "bars": bars,
            "base_y": CHART_H - CHART_PAD, "label_y": CHART_H - 6}


def summary(orders, today=None):
    today = (today or local_now()).date()

    def total_for(days):
        start = today - timedelta(days=days - 1)
        return sum(a for m, a in orders if m.date() >= start)

    month_orders = [(m, a) for m, a in orders if m.date() >= today - timedelta(days=DAYS - 1)]
    count = len(month_orders)
    revenue = sum(a for _, a in month_orders)

    return {
        "today": total_for(1),
        "week": total_for(7),
        "month": revenue,
        "month_count": count,
        "average": revenue // count if count else 0,
    }


def top_products(limit=5):
    rows = db.session.query(
        OrderItem.title,
        func.sum(OrderItem.quantity),
        func.sum(OrderItem.unit_price_rial * OrderItem.quantity),
    ).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Order.status == OrderStatus.PAID
    ).group_by(OrderItem.title).order_by(
        func.sum(OrderItem.quantity).desc(), OrderItem.title
    ).limit(limit).all()

    return [(title, int(qty or 0), int(total or 0)) for title, qty, total in rows]


def low_stock(limit=10):
    return Product.query.filter(
        Product.is_digital.is_(False),
        Product.stock <= LOW_STOCK
    ).order_by(Product.stock, Product.id).limit(limit).all()


def popular_posts(limit=5):
    return Post.query.filter(
        Post.is_published.is_(True)
    ).order_by(Post.view_count.desc(), Post.id.desc()).limit(limit).all()


def total_views():
    return db.session.query(func.coalesce(func.sum(Post.view_count), 0)).scalar() or 0
