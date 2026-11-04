import io
import re
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.customers.models import Customer
from app.modules.products.files import stored_path
from app.modules.products.models import Category, Product
from app.modules.shop.models import Fulfillment, Order, OrderItem, OrderStatus
from config import Config


PASSWORD = "a-very-long-password-123"
BUYER = {"email": "Buyer@Example.test", "password": "buyer-password-1"}
FILE_BYTES = b"PK\x03\x04" + b"secret-content" * 50


class DigitalConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"
    DIGITAL_DOWNLOAD_LIMIT = 3
    DIGITAL_FILE_MAX_MB = 1


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(DigitalConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="نرم‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add_all([
            Product(title="کتاب الکترونیکی", price=200_000, stock=0,
                    category_id=category.id),
            Product(title="کلید امنیتی", price=500_000, stock=5,
                    category_id=category.id),
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


def register(client, email=BUYER["email"], password=BUYER["password"], **extra):
    client.get("/account/captcha.png")
    data = {"full_name": "خریدار تست", "email": email, "password": password,
            "password2": password, "captcha": "ABCDE", "website": ""}
    data.update(extra)
    return client.post("/account/register", data=data)


def make_digital(app, admin, title="کتاب الکترونیکی", data=FILE_BYTES, name="book.zip"):
    with app.app_context():
        pid = Product.query.filter_by(title=title).one().id

    return admin.post(
        f"/products/edit/{pid}",
        data={"title": title, "description": "", "price": "200000", "stock": "0",
              "category_id": "1", "is_digital": "y",
              "product_file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def buy(client, title="کتاب الکترونیکی"):
    """خرید با درگاه آزمایشی؛ آدرس صفحهٔ سفارش را برمی‌گرداند."""
    with client.application.app_context():
        pid = Product.query.filter_by(title=title).one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    response = client.post("/shop/checkout", data={
        "full_name": "خریدار تست", "phone": "", "email": "", "note": ""})
    pay = client.post(response.headers["Location"], data={"result": "ok"})
    callback = client.get(pay.headers["Location"])     # بازگشت از درگاه

    return callback.headers["Location"]


# ---------------------------------------------------------- ثبت‌نام و ورود

def test_register_logs_in_and_normalizes_email(app, client):
    response = register(client)

    assert response.status_code == 302

    with app.app_context():
        customer = Customer.query.one()
        assert customer.email == "buyer@example.test"
        assert customer.password_hash != BUYER["password"]
        assert customer.check_password(BUYER["password"])

    assert client.get("/account/").status_code == 200


def test_register_rejects_bad_input(app, client):
    assert register(client, password="short").status_code == 200
    assert register(client, email="not-an-email").status_code == 200
    assert register(client, captcha="ZZZZZ").status_code == 200
    assert register(client, **{"password2": "different-pass-1"}).status_code == 200

    with app.app_context():
        assert Customer.query.count() == 0


def test_register_honeypot_creates_nothing(app, client):
    register(client, website="http://spam.example")

    with app.app_context():
        assert Customer.query.count() == 0


def test_duplicate_email_is_rejected(app, client):
    register(client)
    other = app.test_client()
    response = register(other, email="buyer@example.test")

    assert response.status_code == 200
    assert "قبلاً حساب ساخته شده" in response.get_data(as_text=True)

    with app.app_context():
        assert Customer.query.count() == 1


def test_login_logout_and_wrong_password(app, client):
    register(client)
    client.post("/account/logout")

    assert client.get("/account/").status_code == 302

    bad = client.post("/account/login", data={"email": BUYER["email"], "password": "wrong-password"})
    assert bad.status_code == 200
    assert "اشتباه است" in bad.get_data(as_text=True)

    good = client.post("/account/login", data=BUYER)
    assert good.status_code == 302
    assert client.get("/account/").status_code == 200


def test_login_is_locked_after_repeated_failures(app, client):
    register(client)
    client.post("/account/logout")

    for _ in range(5):
        client.post("/account/login", data={"email": BUYER["email"], "password": "wrong-password"})

    locked = client.post("/account/login", data=BUYER)

    assert locked.status_code == 429


def test_customer_lockout_does_not_lock_admin(app, client):
    register(client)
    client.post("/account/logout")

    for _ in range(5):
        client.post("/account/login", data={"email": BUYER["email"], "password": "wrong-password"})

    admin = app.test_client()
    admin.get("/admin/captcha.png")
    response = admin.post("/admin/login",
                          data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})

    assert response.status_code == 302


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example", "/\\evil.example"])
def test_login_next_is_not_an_open_redirect(app, client, target):
    register(client)
    client.post("/account/logout")

    response = client.post("/account/login", query_string={"next": target}, data=BUYER)

    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]


def test_customer_and_admin_sessions_are_independent(app, client, admin):
    register(admin, email="admin-and-buyer@example.test")

    assert admin.get("/admin/").status_code == 200
    assert admin.get("/account/").status_code == 200

    admin.post("/account/logout")

    assert admin.get("/admin/").status_code == 200       # مدیر خارج نشد
    assert admin.get("/account/").status_code == 302


def test_change_password(app, client):
    register(client)

    wrong = client.post("/account/password", data={
        "current_password": "nope-nope-1", "password": "new-password-22", "password2": "new-password-22"})
    assert wrong.status_code == 200

    ok = client.post("/account/password", data={
        "current_password": BUYER["password"], "password": "new-password-22", "password2": "new-password-22"})
    assert ok.status_code == 302

    client.post("/account/logout")
    assert client.post("/account/login", data={"email": BUYER["email"], "password": "new-password-22"}).status_code == 302


# ------------------------------------------------------------ محصول فایلی

def test_admin_creates_digital_product_and_file_is_stored_privately(app, admin, client):
    response = make_digital(app, admin)

    assert response.status_code == 302

    with app.app_context():
        product = Product.query.filter_by(title="کتاب الکترونیکی").one()
        assert product.is_digital and product.in_stock
        assert re.fullmatch(r"[a-f0-9]{32}\.zip", product.file_name)
        assert product.file_title == "book.zip"
        assert product.file_size == len(FILE_BYTES)
        assert stored_path(product.file_name).read_bytes() == FILE_BYTES
        name = product.file_name

    # از بیرون در دسترس نیست
    assert client.get(f"/static/{name}").status_code == 404
    assert client.get(f"/products/image/{name}").status_code == 404
    html = client.get("/products/").get_data(as_text=True)
    assert "ناموجود" not in html.split("کتاب الکترونیکی")[1].split("</article>")[0]


def test_digital_product_requires_a_file(app, admin):
    with app.app_context():
        pid = Product.query.filter_by(title="کتاب الکترونیکی").one().id

    response = admin.post(
        f"/products/edit/{pid}",
        data={"title": "کتاب الکترونیکی", "price": "200000", "stock": "0",
              "category_id": "1", "is_digital": "y"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "فایل دانلود را انتخاب کنید" in response.get_data(as_text=True)

    with app.app_context():
        assert Product.query.filter_by(title="کتاب الکترونیکی").one().is_digital is False


@pytest.mark.parametrize("name,data", [("evil.exe", b"MZ"), ("noext", b"abc"), ("empty.zip", b"")])
def test_bad_files_are_rejected(app, admin, name, data):
    make_digital(app, admin, data=data, name=name)

    with app.app_context():
        assert Product.query.filter_by(title="کتاب الکترونیکی").one().file_name is None

    folder = Path(app.instance_path) / "uploads" / "files"
    assert not folder.exists() or list(folder.iterdir()) == []


def test_too_large_file_is_rejected_and_removed(app, admin):
    make_digital(app, admin, data=b"x" * (1024 * 1024 + 10), name="big.zip")

    with app.app_context():
        assert Product.query.filter_by(title="کتاب الکترونیکی").one().file_name is None

    folder = Path(app.instance_path) / "uploads" / "files"
    assert not folder.exists() or list(folder.iterdir()) == []


# ------------------------------------------------------------ خرید و دانلود

def test_checkout_requires_login(app, client):
    with app.app_context():
        pid = Product.query.filter_by(title="کلید امنیتی").one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    response = client.get("/shop/checkout")

    assert response.status_code == 302
    assert "/account/login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]


def test_login_returns_to_checkout_and_keeps_cart(app, client):
    with app.app_context():
        pid = Product.query.filter_by(title="کلید امنیتی").one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "2"})
    register(client)

    response = client.get("/shop/checkout")

    assert response.status_code == 200
    assert "ثبت سفارش" in response.get_data(as_text=True)


def test_digital_purchase_shows_download_immediately(app, admin, client):
    make_digital(app, admin)
    register(client)

    location = buy(client)
    page = client.get(location).get_data(as_text=True)

    assert "دانلود فایل‌ها" in page
    assert "/account/download/" in page

    with app.app_context():
        order = Order.query.one()
        item = order.items[0]
        assert order.status == OrderStatus.PAID
        assert order.customer.email == "buyer@example.test"
        assert item.is_digital
        # سفارش فقط-فایل ارسال ندارد
        assert order.fulfillment == Fulfillment.DELIVERED and order.delivered_at
        # موجودی انبار دست نمی‌خورد
        assert Product.query.filter_by(title="کتاب الکترونیکی").one().stock == 0
        item_id = item.id

    response = client.get(f"/account/download/{item_id}")

    assert response.status_code == 200
    assert response.data == FILE_BYTES
    assert "attachment" in response.headers["Content-Disposition"]
    assert "book.zip" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]

    with app.app_context():
        assert db.session.get(OrderItem, item_id).download_count == 1


def test_download_limit_and_admin_reset(app, admin, client):
    make_digital(app, admin)
    register(client)
    buy(client)

    with app.app_context():
        item_id = OrderItem.query.one().id

    for _ in range(3):
        assert client.get(f"/account/download/{item_id}").status_code == 200

    blocked = client.get(f"/account/download/{item_id}")

    assert blocked.status_code == 302                 # به پنل با پیام برمی‌گردد
    assert "سقف دانلود" in client.get("/account/").get_data(as_text=True)

    with app.app_context():
        order_id = Order.query.one().id

    admin.post(f"/shop/manage/orders/{order_id}/reset-downloads")

    assert client.get(f"/account/download/{item_id}").status_code == 200


def test_resumed_range_download_is_not_counted_again(app, admin, client):
    make_digital(app, admin)
    register(client)
    buy(client)

    with app.app_context():
        item_id = OrderItem.query.one().id

    client.get(f"/account/download/{item_id}")
    part = client.get(f"/account/download/{item_id}", headers={"Range": "bytes=100-"})

    assert part.status_code == 206

    with app.app_context():
        assert db.session.get(OrderItem, item_id).download_count == 1


def test_other_customers_and_guests_cannot_download(app, admin, client):
    make_digital(app, admin)
    register(client)
    buy(client)

    with app.app_context():
        item_id = OrderItem.query.one().id

    stranger = app.test_client()
    register(stranger, email="stranger@example.test")

    assert stranger.get(f"/account/download/{item_id}").status_code == 404

    guest = app.test_client()
    response = guest.get(f"/account/download/{item_id}")

    assert response.status_code == 302 and "/account/login" in response.headers["Location"]

    # لینک عمومی سفارش برای غریبه دکمهٔ دانلود نشان نمی‌دهد
    with app.app_context():
        code = Order.query.one().public_code

    page = stranger.get(f"/shop/order/{code}").get_data(as_text=True)
    assert "/account/download/" not in page


def test_unpaid_order_cannot_be_downloaded(app, admin, client):
    make_digital(app, admin)
    register(client)

    with app.app_context():
        pid = Product.query.filter_by(title="کتاب الکترونیکی").one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    client.post("/shop/checkout", data={"full_name": "خریدار تست", "phone": "", "email": "", "note": ""})

    with app.app_context():
        item_id = OrderItem.query.one().id
        assert Order.query.one().status == OrderStatus.PENDING

    assert client.get(f"/account/download/{item_id}").status_code == 404


def test_digital_cart_is_always_quantity_one(app, admin, client):
    make_digital(app, admin)

    with app.app_context():
        pid = Product.query.filter_by(title="کتاب الکترونیکی").one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "7"})
    client.post(f"/shop/cart/update/{pid}", data={"quantity": "9"})

    html = client.get("/shop/cart").get_data(as_text=True)

    assert "ناموجود" not in html
    assert "فقط" not in html or "عدد موجود" not in html


def test_physical_purchase_still_reserves_stock(app, client):
    register(client)

    with app.app_context():
        pid = Product.query.filter_by(title="کلید امنیتی").one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "2"})
    client.post("/shop/checkout", data={"full_name": "خریدار تست",
                                        "phone": "09121234567", "email": "", "note": ""})

    with app.app_context():
        assert Product.query.filter_by(title="کلید امنیتی").one().stock == 3
        assert Order.query.one().fulfillment == Fulfillment.NEW


def test_deleting_product_with_buyers_is_blocked(app, admin, client):
    make_digital(app, admin)
    register(client)
    buy(client)

    with app.app_context():
        pid = Product.query.filter_by(title="کتاب الکترونیکی").one().id
        name = db.session.get(Product, pid).file_name

    admin.post(f"/products/delete/{pid}")

    with app.app_context():
        assert db.session.get(Product, pid) is not None
        assert stored_path(name).is_file()


def test_deleting_unsold_digital_product_removes_file(app, admin):
    make_digital(app, admin)

    with app.app_context():
        product = Product.query.filter_by(title="کتاب الکترونیکی").one()
        pid, path = product.id, stored_path(product.file_name)

    assert path.is_file()
    admin.post(f"/products/delete/{pid}")

    assert not path.exists()


def test_replacing_file_serves_new_version_and_removes_old(app, admin):
    make_digital(app, admin)

    with app.app_context():
        old = stored_path(Product.query.filter_by(title="کتاب الکترونیکی").one().file_name)

    make_digital(app, admin, data=b"PK\x03\x04new-version", name="book-v2.zip")

    with app.app_context():
        product = Product.query.filter_by(title="کتاب الکترونیکی").one()
        assert product.file_title == "book-v2.zip"
        assert stored_path(product.file_name).read_bytes() == b"PK\x03\x04new-version"

    assert not old.exists()


def test_account_and_download_pages_are_private(app, client):
    register(client)

    for url in ("/account/", "/account/login"):
        response = client.get(url)
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"

    assert "Disallow: /account" in client.get("/robots.txt").get_data(as_text=True)


def test_dashboard_lists_orders_and_files(app, admin, client):
    make_digital(app, admin)
    register(client)
    buy(client)

    html = client.get("/account/").get_data(as_text=True)

    assert "کتاب الکترونیکی" in html
    assert "/account/download/" in html
    assert "3 از 3" in html            # سقف آزمایشی ۳
