from urllib.parse import urlparse

from flask import Blueprint, render_template

from app.modules.content.registry import _EMAIL, https_only
from app.modules.content.service import get_text
from app.modules.slides.models import HomeSlide


home_bp = Blueprint("home", __name__)


def _handle(url):
    """از آدرس پروفایل، شناسهٔ نمایشی (@name) می‌سازد."""
    name = urlparse(url).path.strip("/").split("/")[0] if url else ""
    return f"@{name}" if name else ""


@home_bp.route("/")
def index():
    slides = HomeSlide.query.filter(
        HomeSlide.is_active.is_(True)
    ).order_by(HomeSlide.position, HomeSlide.id).all()

    return render_template("home/index.html", slides=slides)


@home_bp.route("/about")
def about():
    # مقدار ذخیره‌شده هنگام نمایش هم دوباره بررسی می‌شود (دفاع دوم)
    instagram = https_only(get_text("instagram_url"))
    telegram = https_only(get_text("telegram_url"))
    email = get_text("public_email").strip()

    return render_template(
        "home/about.html",
        instagram_url=instagram,
        instagram_handle=_handle(instagram),
        telegram_url=telegram,
        telegram_handle=_handle(telegram),
        email=email if _EMAIL.match(email) else ""
    )
