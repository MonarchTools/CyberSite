import re

from flask import Blueprint, current_app, render_template

from app.modules.slides.models import HomeSlide


home_bp = Blueprint("home", __name__)

_EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")


def _https_only(url):
    """فقط آدرس https پذیرفته می‌شود (جلوگیری از javascript: و data: از .env)."""
    url = (url or "").strip()
    return url if url.lower().startswith("https://") and " " not in url else ""


@home_bp.route("/")
def index():
    slides = HomeSlide.query.filter(
        HomeSlide.is_active.is_(True)
    ).order_by(HomeSlide.position, HomeSlide.id).all()

    return render_template("home/index.html", slides=slides)


@home_bp.route("/about")
def about():
    config = current_app.config
    email = (config.get("PUBLIC_EMAIL") or "").strip()

    return render_template(
        "home/about.html",
        instagram_url=_https_only(config.get("SOCIAL_INSTAGRAM_URL")),
        telegram_url=_https_only(config.get("SOCIAL_TELEGRAM_URL")),
        email=email if _EMAIL.match(email) else ""
    )
