"""robots.txt، sitemap.xml و تصویر پیش‌نمایش لینک (JPEG ۱۲۰۰×۶۳۰)."""

import io
import re
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, request, url_for
from PIL import Image, ImageOps

from app.modules.blog.models import Post
from app.modules.blog.taxonomy import published_categories, published_tags
from app.modules.products.models import Product
from app.security import PRIVATE_PREFIXES
from app.seo import OG_HEIGHT, OG_WIDTH, absolute_url, base_url
from app.uploads import upload_folder


seo_bp = Blueprint("seo", __name__)

SITEMAP_LIMIT = 50000

# kind -> (پوشهٔ آپلود، پسوندهای ممکن)
OG_SOURCES = {
    "blog": ("blog", ("webp",)),
    "products": ("products", ("webp", "jpg", "jpeg", "png")),
}

_OG_NAME = re.compile(r"^([a-f0-9]{32})\.jpg$")


@seo_bp.route("/robots.txt")
def robots():
    lines = ["User-agent: *"]
    lines += [f"Disallow: {prefix}" for prefix in PRIVATE_PREFIXES]
    lines += ["", f"Sitemap: {base_url()}/sitemap.xml", ""]

    response = Response("\n".join(lines), mimetype="text/plain")
    response.headers["Cache-Control"] = "public, max-age=3600"

    return response


def _date(value):
    return value.strftime("%Y-%m-%d") if value else None


def _entry(path, lastmod=None):
    loc = escape(absolute_url(path))
    stamp = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""

    return f"<url><loc>{loc}</loc>{stamp}</url>"


@seo_bp.route("/sitemap.xml")
def sitemap():
    entries = [
        _entry(url_for("home.index")),
        _entry(url_for("home.about")),
        _entry(url_for("contact.index")),
        _entry(url_for("blog.index")),
        _entry(url_for("products.index")),
    ]

    posts = Post.query.filter(
        Post.is_published.is_(True)
    ).order_by(Post.published_at.desc(), Post.id.desc()).limit(SITEMAP_LIMIT).all()

    for post in posts:
        entries.append(_entry(
            url_for("blog.detail", slug=post.slug),
            _date(post.updated_at or post.published_at)
        ))

    # صفحهٔ دسته‌ها و برچسب‌هایی که پست منتشرشده دارند
    for category, _count in published_categories():
        entries.append(_entry(url_for("blog.category", slug=category.slug)))

    for tag, _count in published_tags(limit=200):
        entries.append(_entry(url_for("blog.tag", slug=tag.slug)))

    room = max(SITEMAP_LIMIT - len(entries), 0)

    for product in Product.query.order_by(Product.id.desc()).limit(room).all():
        entries.append(_entry(
            url_for("products.detail", product_id=product.id),
            _date(product.created_at)
        ))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(entries)
        + "</urlset>"
    )

    response = Response(xml, mimetype="application/xml")
    response.headers["Cache-Control"] = "public, max-age=3600"

    return response


def _render_og(path):
    """تصویر را به JPEG با اندازهٔ استاندارد پیش‌نمایش تبدیل می‌کند (برش وسط)."""
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)

        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (14, 20, 38))
            background.paste(image, mask=image.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")

        image = ImageOps.fit(image, (OG_WIDTH, OG_HEIGHT), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)

    return buffer.getvalue()


@seo_bp.route("/og/<kind>/<name>")
def og_image(kind, name):
    """نسخهٔ JPEG عکس پست یا محصول؛ بعضی پیام‌رسان‌ها WEBP را در پیش‌نمایش نشان نمی‌دهند."""
    source = OG_SOURCES.get(kind)
    match = _OG_NAME.fullmatch(name)

    if source is None or match is None:
        abort(404)

    folder = upload_folder(source[0])
    path = next(
        (
            folder / f"{match.group(1)}.{ext}"
            for ext in source[1]
            if (folder / f"{match.group(1)}.{ext}").is_file()
        ),
        None,
    )

    if path is None:
        abort(404)

    try:
        data = _render_og(path)
    except Exception:
        abort(404)

    response = Response(data, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.set_etag(f"{path.stat().st_mtime_ns}-{path.stat().st_size}")

    return response.make_conditional(request)
