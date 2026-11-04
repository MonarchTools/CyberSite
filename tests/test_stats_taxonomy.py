import re
import xml.etree.ElementTree as ET
from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.blog.models import BlogCategory, BlogTag, Post
from app.modules.blog.taxonomy import parse_tags
from app.modules.products.models import Category, Product
from app.modules.shop.models import Order, OrderItem, OrderStatus
from app.modules.stats import service
from app.utils import utcnow_naive
from config import Config


PASSWORD = "a-very-long-password-123"
SITE = "https://site.example.test"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BODY = "متن کافی برای ذخیرهٔ این پست آزمایشی"


class StatsConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SITE_URL = SITE


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(StatsConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="سخت‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add_all([
            Product(title="کلید امنیتی", price=500_000, stock=3, category_id=category.id),
            Product(title="کابل شبکه", price=100_000, stock=50, category_id=category.id),
        ])
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


def post_data(**extra):
    data = {"title": "پست آزمایشی", "slug": "", "excerpt": "", "body": BODY,
            "category_id": "0", "tags_text": "", "is_published": "y"}
    data.update(extra)
    return data


# ------------------------------------------------------------ تجزیهٔ برچسب

def test_parse_tags_dedupes_and_limits():
    tags = parse_tags("پایتون، امنیت, Flask ,flask, ,شبکه   رایانه")

    assert [slug for _name, slug in tags] == ["پایتون", "امنیت", "flask", "شبکه-رایانه"]
    assert len(parse_tags(",".join(str(i) for i in range(30)))) == 8
    assert parse_tags("، ,  ,!!!") == []


# ------------------------------------------------------------ دسته‌بندی

def test_category_management_requires_login(client):
    assert client.get("/blog/categories").status_code in (302, 401)


def test_create_and_delete_category(app, admin):
    response = admin.post("/blog/categories", data={"name": "امنیت شبکه"})

    assert response.status_code == 302

    with app.app_context():
        category = BlogCategory.query.one()
        assert category.slug == "امنیت-شبکه"
        category_id = category.id

    # تکراری ساخته نمی‌شود
    admin.post("/blog/categories", data={"name": "امنیت شبکه"})

    with app.app_context():
        assert BlogCategory.query.count() == 1

    assert "امنیت شبکه" in admin.get("/blog/categories").get_data(as_text=True)

    admin.post(f"/blog/categories/delete/{category_id}")

    with app.app_context():
        assert BlogCategory.query.count() == 0


def test_post_with_category_and_tags(app, admin, client):
    admin.post("/blog/categories", data={"name": "آموزش"})

    with app.app_context():
        category_id = BlogCategory.query.one().id

    response = admin.post("/blog/create", data=post_data(
        category_id=str(category_id), tags_text="پایتون، امنیت"))

    assert response.status_code == 302

    with app.app_context():
        post = Post.query.one()
        assert post.category.name == "آموزش"
        assert [t.name for t in post.tags] == ["امنیت", "پایتون"]

    html = client.get("/blog/پست-آزمایشی").get_data(as_text=True)

    assert "/blog/category/آموزش" in html or "/blog/category/%D8" in html
    assert "#پایتون" in html

    # ویرایش: مقدار برچسب‌ها در فرم پر می‌شود و با ذخیره عوض می‌شود
    edit = admin.get(f"/blog/edit/{post.id}").get_data(as_text=True)

    assert "پایتون" in edit and "امنیت" in edit

    admin.post(f"/blog/edit/{post.id}", data=post_data(
        category_id=str(category_id), tags_text="شبکه"))

    with app.app_context():
        assert [t.name for t in Post.query.one().tags] == ["شبکه"]


def test_category_and_tag_pages_list_only_published_posts(app, admin, client):
    admin.post("/blog/categories", data={"name": "آموزش"})

    with app.app_context():
        category_id = BlogCategory.query.one().id

    admin.post("/blog/create", data=post_data(
        title="منتشر", category_id=str(category_id), tags_text="flask"))
    admin.post("/blog/create", data=post_data(
        title="پیش‌نویس", category_id=str(category_id), tags_text="flask",
        is_published=""))

    category_page = client.get("/blog/category/آموزش")
    tag_page = client.get("/blog/tag/flask")

    for response in (category_page, tag_page):
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "منتشر" in html
        assert "پیش‌نویس" not in html

    assert client.get("/blog/category/نیست").status_code == 404
    assert client.get("/blog/tag/نیست").status_code == 404

    # صفحهٔ اصلی وبلاگ دسته و برچسب را نشان می‌دهد
    index = client.get("/blog/").get_data(as_text=True)

    assert "taxonomy-chip" in index and "#flask" in index


def test_deleting_category_keeps_posts(app, admin):
    admin.post("/blog/categories", data={"name": "آموزش"})

    with app.app_context():
        category_id = BlogCategory.query.one().id

    admin.post("/blog/create", data=post_data(category_id=str(category_id)))
    admin.post(f"/blog/categories/delete/{category_id}")

    with app.app_context():
        post = Post.query.one()
        assert post.category_id is None


def test_sitemap_includes_taxonomy_pages(app, admin, client):
    admin.post("/blog/categories", data={"name": "آموزش"})
    admin.post("/blog/categories", data={"name": "خالی"})

    with app.app_context():
        category_id = BlogCategory.query.filter_by(name="آموزش").one().id

    admin.post("/blog/create", data=post_data(
        category_id=str(category_id), tags_text="flask"))

    root = ET.fromstring(client.get("/sitemap.xml").data)
    urls = [e.text for e in root.findall("s:url/s:loc", NS)]
    joined = "\n".join(urls)

    assert any("/blog/category/" in u and "%" in u or "آموزش" in u for u in urls)
    assert f"{SITE}/blog/tag/flask" in urls
    # دسته بدون پست منتشرشده در نقشه نیست
    assert "خالی" not in joined and "%D8%AE%D8%A7%D9%84%DB%8C" not in joined


# ------------------------------------------------------------ شمارندهٔ بازدید

def make_post(app, **kw):
    with app.app_context():
        post = Post(title="t", slug="t", body=BODY, is_published=True,
                    published_at=utcnow_naive(), **kw)
        db.session.add(post)
        db.session.commit()


def views(app):
    with app.app_context():
        return Post.query.one().view_count


def test_view_counter_counts_visitors_not_bots_or_admin(app, client, admin):
    make_post(app)

    client.get("/blog/t", headers={"User-Agent": "Mozilla/5.0"})
    client.get("/blog/t", headers={"User-Agent": "Mozilla/5.0"})

    assert views(app) == 2

    client.get("/blog/t", headers={"User-Agent": "TelegramBot (like TwitterBot)"})
    client.get("/blog/t", headers={"User-Agent": "Googlebot/2.1"})
    admin.get("/blog/t", headers={"User-Agent": "Mozilla/5.0"})

    assert views(app) == 2


def test_draft_views_are_not_counted(app, admin):
    with app.app_context():
        db.session.add(Post(title="d", slug="d", body=BODY, is_published=False))
        db.session.commit()

    admin.get("/blog/d")

    with app.app_context():
        assert Post.query.one().view_count == 0


# ------------------------------------------------------------ آمار

def test_stats_requires_login(client):
    assert client.get("/admin/stats/").status_code in (302, 401)


def add_order(app, amount, days_ago=0, status=OrderStatus.PAID, title="کلید امنیتی", qty=1):
    with app.app_context():
        order = Order(
            status=status, total_rial=amount, full_name="خریدار", phone="09120000000",
            paid_at=utcnow_naive() - timedelta(days=days_ago, minutes=1)
            if status == OrderStatus.PAID else None,
        )
        order.items.append(OrderItem(
            title=title, unit_price_rial=amount // qty, quantity=qty))
        db.session.add(order)
        db.session.commit()


def test_stats_page_renders_with_sales(app, admin):
    add_order(app, 500_000, days_ago=0, qty=2)
    add_order(app, 300_000, days_ago=3, title="کابل شبکه")
    add_order(app, 999_999, days_ago=0, status=OrderStatus.PENDING)   # شمرده نمی‌شود
    make_post(app)

    response = admin.get("/admin/stats/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<svg" in html and "chart-bar" in html
    assert "کلید امنیتی" in html and "کابل شبکه" in html
    assert "999,999" not in html
    assert "ناموجود" not in html          # موجودی همه > ۰
    assert 'style="' not in html           # CSP: بدون style درون‌خطی


def test_stats_page_renders_empty(admin):
    response = admin.get("/admin/stats/")

    assert response.status_code == 200
    assert "هنوز فروشی ثبت نشده است" in response.get_data(as_text=True)


def test_stats_summary_and_series(app):
    add_order(app, 500_000)
    add_order(app, 250_000, days_ago=2)
    add_order(app, 100_000, status=OrderStatus.FAILED)

    with app.app_context():
        orders = service.paid_orders_since(366)

        summary = service.summary(orders)
        daily = service.daily_series(orders)
        monthly = service.monthly_series(orders)

    assert len(orders) == 2
    assert summary["month"] == 750_000 and summary["month_count"] == 2
    assert summary["average"] == 375_000
    assert len(daily) == 30 and len(monthly) == 12
    assert sum(item[1] for item in daily) == 750_000


def test_top_products_and_low_stock(app):
    add_order(app, 500_000, title="کلید امنیتی", qty=2)
    add_order(app, 100_000, title="کابل شبکه", qty=1)

    with app.app_context():
        db.session.get(Product, 1).stock = 0
        db.session.commit()

        top = service.top_products()
        low = service.low_stock()

    assert top[0][0] == "کلید امنیتی" and top[0][1] == 2
    assert [p.title for p in low] == ["کلید امنیتی"]


def test_dashboard_links_to_stats(admin):
    assert "/admin/stats/" in admin.get("/admin/").get_data(as_text=True)


def test_stats_bar_chart_geometry():
    series = [(f"d{i}", i * 100, 1) for i in range(10)]
    chart = service.bar_chart(series)
    xs = [bar["x"] for bar in chart["bars"]]

    assert xs == sorted(xs, reverse=True)           # قدیمی‌تر سمت راست
    assert all(0 <= x <= chart["width"] for x in xs)
    assert chart["bars"][-1]["h"] > chart["bars"][1]["h"]
