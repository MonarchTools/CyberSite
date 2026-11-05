import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.customers.models import Customer
from app.modules.products.models import Category, Product
from app.modules.wishlist.models import WishlistItem
from config import Config


PASSWORD = "a-very-long-password-123"


class WishConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(WishConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="سخت‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add_all([
            Product(title="کلید امنیتی", price=500_000, stock=5,
                    category_id=category.id),
            Product(title="کابل شبکه", price=90_000, stock=0,
                    category_id=category.id),
            Customer(email="a@example.test", full_name="الف", password_hash="x"),
            Customer(email="b@example.test", full_name="ب", password_hash="x"),
        ])
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(app, email="a@example.test"):
    client = app.test_client()

    with app.app_context():
        cid = Customer.query.filter_by(email=email).one().id

    with client.session_transaction() as sess:
        sess["customer_id"] = cid

    return client


@pytest.fixture()
def client(app):
    return login(app)


def items(app):
    with app.app_context():
        return sorted(
            (i.customer_id, i.product_id) for i in WishlistItem.query.all()
        )


def test_toggle_adds_then_removes(app, client):
    r = client.post("/account/wishlist/toggle/1", data={"next": "/products/1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/products/1")
    assert items(app) == [(1, 1)]

    client.post("/account/wishlist/toggle/1")
    assert items(app) == []


def test_each_customer_has_own_list(app, client):
    client.post("/account/wishlist/toggle/1")
    other = login(app, "b@example.test")
    other.post("/account/wishlist/toggle/2")

    assert items(app) == [(1, 1), (2, 2)]

    page = client.get("/account/wishlist/").get_data(as_text=True)
    assert "کلید امنیتی" in page and "کابل شبکه" not in page


def test_guest_is_sent_to_login_and_nothing_saved(app):
    guest = app.test_client()
    r = guest.post("/account/wishlist/toggle/1", data={"next": "/products/1"})

    assert r.status_code == 302
    assert "/account/login" in r.headers["Location"]
    assert "next=%2Fproducts%2F1" in r.headers["Location"]
    assert items(app) == []

    assert guest.get("/account/wishlist/").status_code == 302


def test_unknown_product_404_and_open_redirect_blocked(app, client):
    assert client.post("/account/wishlist/toggle/999").status_code == 404

    r = client.post("/account/wishlist/toggle/1", data={"next": "https://evil.example/"})
    assert r.headers["Location"].endswith("/products/1")

    r = client.post("/account/wishlist/toggle/1", data={"next": "//evil.example/"})
    assert r.headers["Location"].endswith("/products/1")


def test_hearts_reflect_state_on_product_pages(app, client):
    assert 'aria-pressed="false"' in client.get("/products/1").get_data(as_text=True)

    client.post("/account/wishlist/toggle/1")

    assert 'aria-pressed="true"' in client.get("/products/1").get_data(as_text=True)
    assert 'aria-pressed="true"' in client.get("/products/").get_data(as_text=True)


def test_guest_sees_empty_hearts(app):
    page = app.test_client().get("/products/1").get_data(as_text=True)
    assert 'aria-pressed="false"' in page


def test_wishlist_page_is_private_and_has_cart_button(app, client):
    client.post("/account/wishlist/toggle/1")
    client.post("/account/wishlist/toggle/2")

    r = client.get("/account/wishlist/")
    html = r.get_data(as_text=True)

    assert "no-store" in r.headers["Cache-Control"]
    assert "/shop/cart/add/1" in html          # موجود: دکمهٔ سبد
    assert "/shop/cart/add/2" not in html      # ناموجود: بدون دکمه
    assert "ناموجود" in html


def test_deleting_product_removes_wishlist_rows(app, client):
    client.post("/account/wishlist/toggle/2")

    admin = app.test_client()
    admin.get("/admin/captcha.png")
    admin.post("/admin/login",
               data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    admin.post("/products/delete/2")

    assert items(app) == []


def test_limit_per_customer(app, client, monkeypatch):
    from app.modules.wishlist import routes

    monkeypatch.setattr(routes, "MAX_ITEMS", 1)
    client.post("/account/wishlist/toggle/1")
    client.post("/account/wishlist/toggle/2")

    assert items(app) == [(1, 1)]
