import io
import re
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.blog.models import Post, PostImage
from app.modules.products.models import Category, Product
from app.utils import utcnow_naive
from config import Config


PASSWORD = "a-very-long-password-123"
SITE = "https://site.example.test"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SeoConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SITE_URL = SITE


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(SeoConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="سخت‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add(Product(title="کلید امنیتی", price=500_000, stock=3,
                               category_id=category.id))
        now = utcnow_naive()
        db.session.add_all([
            Post(title="پست منتشرشده", slug="published", body="متن پست",
                 is_published=True, published_at=now),
            Post(title="پیش‌نویس", slug="draft", body="هنوز آماده نیست",
                 is_published=False),
        ])
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def put_image(app, folder, name, fmt="WEBP", size=(300, 900), color=(200, 30, 30)):
    from app.uploads import upload_folder

    with app.app_context():
        Image.new("RGB", size, color).save(upload_folder(folder) / name, fmt)


def meta(html, key):
    match = re.search(
        rf'<meta (?:property|name)="{re.escape(key)}" content="([^"]*)"', html
    )
    return match.group(1) if match else None


# ------------------------------------------------------------ robots / sitemap

def test_robots_txt(client):
    response = client.get("/robots.txt")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "Disallow: /admin" in text
    assert "Disallow: /shop/checkout" in text
    assert f"Sitemap: {SITE}/sitemap.xml" in text


def test_sitemap_lists_public_pages_but_not_drafts(client):
    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/xml"

    root = ET.fromstring(response.data)
    urls = [e.text for e in root.findall("s:url/s:loc", NS)]

    assert f"{SITE}/" in urls
    assert f"{SITE}/blog/" in urls
    assert f"{SITE}/products/" in urls
    assert f"{SITE}/about" in urls
    assert f"{SITE}/blog/published" in urls
    assert f"{SITE}/products/1" in urls
    assert all("draft" not in u for u in urls)
    assert all("/admin" not in u and "/shop/" not in u for u in urls)


# -------------------------------------------------------------- پیش‌نمایش لینک

def test_post_has_open_graph_tags(app, client):
    name = "a" * 32 + ".webp"
    put_image(app, "blog", name)

    with app.app_context():
        post = Post.query.filter_by(slug="published").first()
        post.cover_image = name
        db.session.commit()

    html = client.get("/blog/published").get_data(as_text=True)

    assert meta(html, "og:type") == "article"
    assert meta(html, "og:title") == "پست منتشرشده | CyberSite"
    assert meta(html, "og:url") == f"{SITE}/blog/published"
    assert meta(html, "og:image") == f"{SITE}/og/blog/{'a' * 32}.jpg"
    assert meta(html, "twitter:card") == "summary_large_image"
    assert f'<link rel="canonical" href="{SITE}/blog/published">' in html
    assert 'name="robots"' not in html


def test_post_without_image_uses_default_image(client):
    html = client.get("/blog/published").get_data(as_text=True)

    assert re.fullmatch(
        re.escape(f"{SITE}/static/og-default.jpg") + r"(\?v=\d+)?",
        meta(html, "og:image"),
    )
    assert client.get("/static/og-default.jpg").status_code == 200


def test_product_has_open_graph_tags(app, client):
    name = "b" * 32 + ".webp"
    put_image(app, "products", name)

    with app.app_context():
        db.session.get(Product, 1).image_filename = name
        db.session.commit()

    html = client.get("/products/1").get_data(as_text=True)

    assert meta(html, "og:type") == "product"
    assert meta(html, "og:image") == f"{SITE}/og/products/{'b' * 32}.jpg"
    assert meta(html, "og:description")


def test_og_image_is_a_1200x630_jpeg(app, client):
    put_image(app, "blog", "c" * 32 + ".webp", size=(300, 900))

    response = client.get(f"/og/blog/{'c' * 32}.jpg")

    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"

    image = Image.open(io.BytesIO(response.data))

    assert image.format == "JPEG"
    assert image.size == (1200, 630)


def test_og_image_supports_legacy_product_png(app, client):
    put_image(app, "products", "d" * 32 + ".png", fmt="PNG")

    assert client.get(f"/og/products/{'d' * 32}.jpg").status_code == 200


@pytest.mark.parametrize("path", [
    "/og/blog/../../etc/passwd",
    "/og/blog/evil.jpg",
    "/og/blog/" + "e" * 32 + ".jpg",       # فایل وجود ندارد
    "/og/blog/" + "e" * 32 + ".png",
    "/og/other/" + "e" * 32 + ".jpg",
])
def test_og_image_rejects_bad_requests(client, path):
    assert client.get(path).status_code == 404


def test_og_image_corrupt_file_is_404(app, client):
    from app.uploads import upload_folder

    with app.app_context():
        (upload_folder("blog") / ("f" * 32 + ".webp")).write_bytes(b"not an image")

    assert client.get(f"/og/blog/{'f' * 32}.jpg").status_code == 404


# ----------------------------------------------------------------- noindex

def test_draft_post_is_noindex_for_admin(app, client):
    admin = app.test_client()
    admin.get("/admin/captcha.png")
    admin.post("/admin/login",
               data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})

    html = admin.get("/blog/draft").get_data(as_text=True)

    assert meta(html, "robots") == "noindex, nofollow"


@pytest.mark.parametrize("url", [
    "/blog/?q=test",
    "/products/?q=test",
    "/products/?category=1",
    "/products/?sort=price_asc",
    "/products/?in_stock=1",
])
def test_search_and_filter_pages_are_noindex(client, url):
    html = client.get(url).get_data(as_text=True)

    assert meta(html, "robots") == "noindex, follow"
    # canonical به صفحهٔ اصلی بدون فیلتر اشاره می‌کند
    assert "?q=" not in re.search(r'rel="canonical" href="([^"]*)"', html).group(1)


def test_plain_lists_are_indexable_and_page_two_keeps_page_param(client):
    html = client.get("/blog/").get_data(as_text=True)

    assert meta(html, "robots") is None
    assert f'rel="canonical" href="{SITE}/blog/"' in html

    page2 = client.get("/blog/?page=2").get_data(as_text=True)

    assert f'rel="canonical" href="{SITE}/blog/?page=2"' in page2


def test_error_pages_are_noindex(client):
    response = client.get("/blog/no-such-post")

    assert response.status_code == 404
    assert meta(response.get_data(as_text=True), "robots") == "noindex, nofollow"


@pytest.mark.parametrize("url", ["/admin/login", "/shop/cart", "/shop/checkout"])
def test_private_paths_send_noindex_header(client, url):
    response = client.get(url)

    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_public_pages_have_no_noindex_header(client):
    assert "X-Robots-Tag" not in client.get("/blog/published").headers
    assert "X-Robots-Tag" not in client.get("/sitemap.xml").headers


def test_base_url_falls_back_to_request_host(monkeypatch, app):
    app.config["SITE_URL"] = ""

    html = app.test_client().get("/blog/published").get_data(as_text=True)

    assert meta(html, "og:url") == "http://localhost/blog/published"
