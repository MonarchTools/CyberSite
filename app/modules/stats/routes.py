from flask import Blueprint, render_template
from flask_login import login_required

from app.modules.stats import service


stats_bp = Blueprint("stats", __name__, url_prefix="/admin/stats")


@stats_bp.route("/")
@login_required
def index():
    orders = service.paid_orders_since(366)

    return render_template(
        "admin/stats.html",
        summary=service.summary(orders),
        daily=service.bar_chart(service.daily_series(orders), label_every=5),
        monthly=service.bar_chart(service.monthly_series(orders), label_every=2),
        top_products=service.top_products(),
        low_stock=service.low_stock(),
        popular_posts=service.popular_posts(),
        total_views=service.total_views(),
        low_stock_limit=service.LOW_STOCK,
    )
