import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.blog.markup import render_body
from app.modules.blog.models import Post, PostImage
from app.modules.products.models import Category, Product, ProductImage
from app.utils import utcnow_naive
from config import Config


PASSWORD = "a-very-long-password-123"
HEX = "a" * 32


class MediaConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SITE_URL = "https://site.example.test"


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(MediaConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="سخت‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add(Product(title="کلید امنیتی", price=500_000, stock=3,
                               category_id=category.id))
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin(app):
    c = app.test_client()
    c.get("/admin/captcha.png")
    c.post("/admin/login",
           data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    return c


def png(color=(200, 30, 30), size=(40, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def upload(data=None, name="x.png"):
    return (io.BytesIO(data if data is not None else png()), name)


def stored(app, folder):
    path = Path(app.instance_path) / "uploads" / folder
    return sorted(p.name for p in path.iterdir()) if path.exists() else []


PRODUCT = {"title": "کلید امنیتی", "price": "500000", "stock": "3",
           "description": "", "category_id": "1"}


# ---------------------------------------------------------- گالری محصول

def test_gallery_images_are_saved_and_shown(app, admin, client):
    response = admin.post(
        "/products/edit/1",
        data={**PRODUCT, "gallery": [upload(png((1, 2, 3))), upload(png((9, 9, 9)))]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302

    with app.app_context():
        product = db.session.get(Product, 1)
        names = [image.filename for image in product.gallery]

    assert len(names) == 2
    assert all(re.fullmatch(r"[a-f0-9]{32}\.webp", n) for n in names)
    assert sorted(stored(app, "products")) == sorted(names)

    html = client.get("/products/1").get_data(as_text=True)

    assert "data-gallery-thumb" in html
    assert all(n in html for n in names)
    assert client.get(f"/products/image/{names[0]}").status_code == 200


def test_single_image_has_no_thumbnails(app, admin, client):
    admin.post("/products/edit/1",
               data={**PRODUCT, "gallery": [upload()]},
               content_type="multipart/form-data")

    html = client.get("/products/1").get_data(as_text=True)

    assert "<img" in html
    assert "data-gallery-thumb" not in html


def test_gallery_delete_removes_row_and_file(app, admin):
    admin.post("/products/edit/1", data={**PRODUCT, "gallery": [upload(), upload(png((5, 5, 5)))]},
               content_type="multipart/form-data")

    with app.app_context():
        first = db.session.get(Product, 1).gallery[0]
        first_id, first_name = first.id, first.filename

    admin.post("/products/edit/1", data={**PRODUCT, "delete_image": [str(first_id), "999", "abc"]},
               content_type="multipart/form-data")

    with app.app_context():
        remaining = [i.filename for i in db.session.get(Product, 1).gallery]

    assert len(remaining) == 1 and first_name not in remaining
    assert stored(app, "products") == sorted(remaining)


def test_gallery_limit_and_fake_files_are_rejected(app, admin):
    too_many = [upload(png((i, i, i))) for i in range(9)]
    admin.post("/products/edit/1", data={**PRODUCT, "gallery": too_many},
               content_type="multipart/form-data")

    admin.post("/products/edit/1",
               data={**PRODUCT, "gallery": [upload(png()), upload(b"not an image", "evil.png")]},
               content_type="multipart/form-data")

    with app.app_context():
        assert db.session.get(Product, 1).gallery == []

    # هیچ فایل نیمه‌کاره‌ای باقی نمی‌ماند
    assert stored(app, "products") == []


def test_deleting_product_removes_gallery_files(app, admin):
    admin.post("/products/edit/1", data={**PRODUCT, "gallery": [upload(), upload(png((7, 7, 7)))]},
               content_type="multipart/form-data")

    assert len(stored(app, "products")) == 2

    assert admin.post("/products/delete/1").status_code == 302

    assert stored(app, "products") == []

    with app.app_context():
        assert ProductImage.query.count() == 0


def test_gallery_upload_requires_login(app, client):
    response = client.post("/products/edit/1", data={**PRODUCT, "gallery": [upload()]},
                           content_type="multipart/form-data")

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]
    assert stored(app, "products") == []


def test_anonymous_big_bodies_are_refused(app, client):
    big = b"x" * (600 * 1024)
    response = client.post("/contact/", data={"message": big},
                           content_type="application/x-www-form-urlencoded")

    assert response.status_code == 413


# ------------------------------------------------------ عکس داخل متن پست

def post_data(**extra):
    return {"title": "پست آزمایشی", "slug": "", "excerpt": "",
            "body": "متن کافی برای پست آزمایشی وبلاگ.", "is_published": "y", **extra}


def test_inline_images_are_saved_listed_and_rendered(app, admin, client):
    response = admin.post("/blog/create",
                          data=post_data(images=[upload(), upload(png((9, 9, 9)))]),
                          content_type="multipart/form-data")

    assert response.status_code == 302

    with app.app_context():
        post = Post.query.one()
        names = [i.filename for i in post.body_images]
        post_id = post.id

    assert len(names) == 2 and sorted(stored(app, "blog")) == sorted(names)

    # صفحهٔ ویرایش کد درج را نشان می‌دهد
    html = admin.get(f"/blog/edit/{post_id}").get_data(as_text=True)
    assert f"/blog/image/{names[0]}" in html

    body = f"متن کافی برای پست.\n\n![نمودار اول](/blog/image/{names[0]})\n\nپایان متن."
    admin.post(f"/blog/edit/{post_id}", data=post_data(body=body),
               content_type="multipart/form-data")

    page = client.get("/blog/post").get_data(as_text=True) if False else None
    with app.app_context():
        slug = Post.query.one().slug

    page = client.get(f"/blog/{slug}").get_data(as_text=True)

    assert f'<img src="/blog/image/{names[0]}" alt="نمودار اول" loading="lazy">' in page
    assert client.get(f"/blog/image/{names[0]}").status_code == 200


def test_external_or_foreign_image_urls_are_not_rendered():
    for bad in (
        "![x](https://evil.example/a.png)",
        f"![x](/blog/image/../../etc/passwd)",
        f"![x](/blog/image/{HEX}.png)",
        f'![x](/blog/image/{HEX}.webp" onerror="alert(1))',
    ):
        html = str(render_body(bad))
        assert "<img" not in html and "<figure" not in html


def test_inline_image_alt_is_escaped():
    html = str(render_body(f"![<script>x</script>](/blog/image/{HEX}.webp)"))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_inline_image_limit_fake_files_and_cleanup(app, admin):
    admin.post("/blog/create",
               data=post_data(images=[upload(png((i, i, i))) for i in range(13)]),
               content_type="multipart/form-data")
    admin.post("/blog/create",
               data=post_data(images=[upload(), upload(b"nope", "evil.png")]),
               content_type="multipart/form-data")

    with app.app_context():
        assert Post.query.count() == 0

    assert stored(app, "blog") == []


def test_delete_inline_image_and_post_cleanup(app, admin):
    admin.post("/blog/create", data=post_data(images=[upload(), upload(png((4, 4, 4)))]),
               content_type="multipart/form-data")

    with app.app_context():
        post = Post.query.one()
        first = post.body_images[0]
        post_id, first_id, first_name = post.id, first.id, first.filename

    admin.post(f"/blog/edit/{post_id}", data=post_data(delete_body_image=[str(first_id), "zzz"]),
               content_type="multipart/form-data")

    with app.app_context():
        left = [i.filename for i in Post.query.one().body_images]

    assert len(left) == 1 and first_name not in left
    assert stored(app, "blog") == left

    admin.post(f"/blog/delete/{post_id}")

    assert stored(app, "blog") == []

    with app.app_context():
        assert PostImage.query.count() == 0


# ------------------------------------------------------ جستجو و RSS

def make_posts(app):
    with app.app_context():
        now = utcnow_naive()
        db.session.add_all([
            Post(title="آموزش پایتون", slug="python", body="متن دربارهٔ برنامه‌نویسی پایتون و فلask",
                 is_published=True, published_at=now),
            Post(title="امنیت شبکه", slug="security", body="درباره فایروال 100%_ امن",
                 is_published=True, published_at=now),
            Post(title="پیش‌نویس پایتون", slug="draft", body="پایتون پنهان",
                 is_published=False),
        ])
        db.session.commit()


def test_search_by_title_and_body(app, client):
    make_posts(app)

    html = client.get("/blog/?q=پایتون").get_data(as_text=True)

    assert "آموزش پایتون" in html
    assert "امنیت شبکه" not in html
    assert "پیش‌نویس پایتون" not in html          # پیش‌نویس هرگز در جستجو نیست
    assert "1 نتیجه" in html or "۱ نتیجه" in html

    assert "امنیت شبکه" in client.get("/blog/?q=فایروال").get_data(as_text=True)


def test_search_treats_wildcards_literally_and_handles_empty(app, client):
    make_posts(app)

    assert "امنیت شبکه" in client.get("/blog/?q=100%25_").get_data(as_text=True)

    html = client.get("/blog/?q=%25").get_data(as_text=True)
    assert "آموزش پایتون" not in html

    assert "پیدا نشد" in client.get("/blog/?q=zzzzzz").get_data(as_text=True)
    assert client.get("/blog/?q=" + "x" * 500).status_code == 200


def test_search_term_is_escaped_in_page(app, client):
    make_posts(app)

    html = client.get("/blog/?q=<script>alert(1)</script>").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html


def test_rss_feed_is_valid_and_lists_only_published(app, client):
    make_posts(app)

    response = client.get("/blog/feed.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/rss+xml"

    root = ET.fromstring(response.data)        # XML معتبر
    items = root.findall("./channel/item")
    titles = [i.findtext("title") for i in items]

    assert sorted(titles) == ["آموزش پایتون", "امنیت شبکه"]
    assert all(i.findtext("link").startswith("https://site.example.test/blog/")
               for i in items)
    assert items[0].findtext("pubDate")


def test_rss_feed_escapes_content_and_handles_empty(app, client):
    assert ET.fromstring(client.get("/blog/feed.xml").data).find("./channel") is not None

    with app.app_context():
        db.session.add(Post(title="a & <b> \x01 عنوان", slug="x", body="متن <script> & \x02 کافی",
                            is_published=True, published_at=utcnow_naive()))
        db.session.commit()

    root = ET.fromstring(client.get("/blog/feed.xml").data)

    assert "<b>" in root.find("./channel/item/title").text
    assert "\x01" not in root.find("./channel/item/title").text


def test_blog_page_advertises_feed(client):
    html = client.get("/blog/").get_data(as_text=True)

    assert 'type="application/rss+xml"' in html
    assert "/blog/feed.xml" in html
