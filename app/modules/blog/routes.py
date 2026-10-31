
from flask import Blueprint, render_template

blog_bp = Blueprint(
    "blog",
    __name__,
    url_prefix="/blog"
)


@blog_bp.route("/")
def index():
    return render_template(
        "placeholder.html",
        page_title="وبلاگ"
    )
