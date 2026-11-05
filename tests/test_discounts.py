from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.customers.models import Customer
from app.modules.discounts import service as discounts
from app.modules.discounts.models import DiscountCode
from app.modules.products.models import Category, Product
from app.modules.shop.models import Order, OrderStatus
from app.modules.shop import services as shop_services
from app.utils import utcnow_naive
from config import Config


PASSWORD = "a-very-long-password-123"
PRICE = 500_000


class DiscountConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(DiscountConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        category = Category(name="سخت‌افزار")
        db.session.add_all([admin, category])
        db.session.flush()
        db.session.add(Product(title="کلید امنیتی", price=PRICE, stock=20,
                               category_id=category.id))
        db.session.add(Customer(email="a@example.test", full_name="الف",
                                password_hash="x"))
        db.session.add(Customer(email="b@example.test", full_name="ب",
                                password_hash="x"))
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


@pytest.fixture()
def admin(app):
    c = app.test_client()
    c.get("/admin/captcha.png")
    c.post("/admin/login",
           data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    return c


def add_code(app, **overrides):
    data = {"code": "SAVE10", "kind": "percent", "value": 10}
    data.update(overrides)

    with app.app_context():
        code = DiscountCode(**data)
        db.session.add(code)
        db.session.commit()
        return code.id


def get_code(app, code_id=1):
    with app.app_context():
        return db.session.get(DiscountCode, code_id)


def to_cart(client, quantity=1):
    client.post("/shop/cart/add/1", data={"quantity": str(quantity)})


def apply(client, code="SAVE10"):
    return client.post("/shop/cart/discount", data={"code": code},
                       follow_redirects=True).get_data(as_text=True)


def checkout(client):
    return client.post("/shop/checkout", data={
        "full_name": "خریدار تست", "phone": "09121234567", "email": "", "note": ""})


def pay(client, response, ok=True):
    result = client.post(response.headers["Location"],
                         data={"result": "ok" if ok else "no"})
    return client.get(result.headers["Location"])


def only_order(app):
    with app.app_context():
        order = Order.query.one()
        return (order.total_rial, order.discount_rial, order.discount_code,
                order.status, order.subtotal_rial)


# ---------------------------------------------------------------- اعمال کد

def test_percent_code_is_applied_through_payment(app, client):
    add_code(app)
    to_cart(client)

    page = apply(client)
    assert "کد تخفیف اعمال شد" in page
    assert "SAVE10" in page

    response = checkout(client)
    assert response.status_code == 302

    assert only_order(app) == (450_000, 50_000, "SAVE10", OrderStatus.PENDING, 500_000)
    assert get_code(app).used_count == 1

    callback = pay(client, response)
    assert only_order(app)[3] == OrderStatus.PAID
    assert get_code(app).used_count == 1

    order_page = client.get(callback.headers["Location"]).get_data(as_text=True)
    assert "SAVE10" in order_page


def test_code_is_case_and_digit_insensitive(app, client):
    add_code(app, code="OFF-20", value=20)
    to_cart(client)

    assert "کد تخفیف اعمال شد" in apply(client, "  off-۲۰ ")


def test_fixed_code_and_percent_cap(app, client):
    add_code(app, code="FIX", kind="fixed", value=70_000)
    add_code(app, code="CAP", kind="percent", value=50, max_discount_rial=30_000)
    to_cart(client)

    apply(client, "FIX")
    checkout(client)
    assert only_order(app)[:3] == (430_000, 70_000, "FIX")

    with app.app_context():
        Order.query.delete()
        db.session.commit()

    client2 = login(app)
    to_cart(client2)
    apply(client2, "CAP")
    checkout(client2)
    assert only_order(app)[:3] == (470_000, 30_000, "CAP")


def test_discount_never_goes_below_minimum_payment(app, client):
    add_code(app, code="HUGE", kind="fixed", value=900_000)
    to_cart(client)

    apply(client, "HUGE")
    checkout(client)

    total, discount, *_ = only_order(app)
    assert total == app.config["MIN_PAYMENT_RIAL"]
    assert discount == PRICE - app.config["MIN_PAYMENT_RIAL"]


@pytest.mark.parametrize("overrides, text", [
    ({"is_active": False}, "کد تخفیف معتبر نیست"),
    ({"expires_at": utcnow_naive() - timedelta(days=1)}, "مهلت"),
    ({"max_uses": 1, "used_count": 1}, "ظرفیت"),
    ({"min_order_rial": 5_000_000}, "حداقل"),
])
def test_unusable_codes_are_rejected(app, client, overrides, text):
    add_code(app, **overrides)
    to_cart(client)

    page = apply(client)
    assert text in page

    checkout(client)
    assert only_order(app)[1] == 0   # بدون تخفیف ثبت شد


def test_unknown_code_is_rejected_and_throttled(app, client):
    to_cart(client)

    assert "کد تخفیف معتبر نیست" in apply(client, "NOPE")

    for _ in range(6):
        page = apply(client, "NOPE")

    assert "دقیقهٔ دیگر" in page


def test_once_per_customer(app):
    add_code(app)

    first = login(app)
    to_cart(first)
    apply(first)
    pay(first, checkout(first))

    again = login(app)
    to_cart(again)
    assert "قبلاً از این کد استفاده" in apply(again)

    other = login(app, "b@example.test")
    to_cart(other)
    assert "کد تخفیف اعمال شد" in apply(other)


def test_failed_payment_releases_usage(app, client):
    add_code(app, max_uses=1)
    to_cart(client)
    apply(client)

    pay(client, checkout(client), ok=False)

    assert only_order(app)[3] == OrderStatus.FAILED
    assert get_code(app).used_count == 0


def test_expired_order_releases_usage(app, client):
    add_code(app)
    to_cart(client)
    apply(client)
    checkout(client)

    with app.app_context():
        order = Order.query.one()
        order.created_at = utcnow_naive() - timedelta(hours=3)
        db.session.commit()

        shop_services.expire_stale_orders()

    assert get_code(app).used_count == 0


def test_capacity_is_reserved_atomically(app, client):
    add_code(app, max_uses=1)

    with app.app_context():
        assert discounts.reserve_usage(1) is True
        assert discounts.reserve_usage(1) is False
        discounts.release_usage(1)
        assert discounts.reserve_usage(1) is True


def test_code_removed_if_it_becomes_invalid_before_checkout(app, client):
    add_code(app)
    to_cart(client)
    apply(client)

    with app.app_context():
        db.session.get(DiscountCode, 1).is_active = False
        db.session.commit()

    response = checkout(client)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/shop/cart")
    with app.app_context():
        assert Order.query.count() == 0


def test_remove_code(app, client):
    add_code(app)
    to_cart(client)
    apply(client)

    client.post("/shop/cart/discount/remove")
    checkout(client)

    assert only_order(app)[1] == 0


# ------------------------------------------------------------ پنل مدیر

def form(**overrides):
    data = {"code": "new-code", "kind": "percent", "value": "15",
            "min_order_rial": "", "max_discount_rial": "", "max_uses": "",
            "once_per_customer": "y", "expires_on": "", "is_active": "y"}
    data.update(overrides)
    return data


def test_admin_pages_require_login(client):
    for path in ("/discounts/manage", "/discounts/create"):
        assert client.get(path).status_code == 302


def test_admin_creates_edits_toggles_and_deletes(app, admin):
    assert admin.get("/discounts/manage").status_code == 200

    response = admin.post("/discounts/create", data=form())
    assert response.status_code == 302

    code = get_code(app)
    assert code.code == "NEW-CODE" and code.value == 15 and code.is_active

    assert admin.get("/discounts/edit/1").status_code == 200
    admin.post("/discounts/edit/1", data=form(value="25", max_uses="10",
                                              expires_on="2099-12-31"))
    code = get_code(app)
    assert code.value == 25 and code.max_uses == 10
    assert code.expires_at.year == 2099

    admin.post("/discounts/toggle/1")
    assert get_code(app).is_active is False

    admin.post("/discounts/delete/1")
    assert get_code(app) is None


def test_admin_rejects_bad_and_duplicate_codes(app, admin):
    assert admin.post("/discounts/create", data=form(value="150")).status_code == 200
    assert admin.post("/discounts/create", data=form(code="a b")).status_code == 200

    admin.post("/discounts/create", data=form())
    assert admin.post("/discounts/create", data=form()).status_code == 200

    with app.app_context():
        assert DiscountCode.query.count() == 1


def test_used_code_cannot_be_deleted(app, admin, client):
    add_code(app)
    to_cart(client)
    apply(client)
    checkout(client)

    admin.post("/discounts/delete/1")
    assert get_code(app) is not None
