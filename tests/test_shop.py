import re

import pytest

from app import create_app
from app.extensions import db
from app.modules.products.models import Category, Product
from app.modules.shop.models import Order, OrderStatus
from config import Config


class ShopTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"
    PRODUCTS_PER_PAGE = 3


@pytest.fixture()
def app():
    app = create_app(ShopTestConfig)

    with app.app_context():
        hardware = Category(name="سخت‌افزار")
        software = Category(name="نرم‌افزار")
        db.session.add_all([hardware, software])
        db.session.flush()

        db.session.add_all([
            Product(title="کلید امنیتی", description="کلید USB",
                    price=500_000, stock=5, category_id=hardware.id),
            Product(title="مودم قدیمی", price=100_000, stock=0,
                    category_id=hardware.id),
            Product(title="آنتی‌ویروس", description="۱۰۰٪ محافظت",
                    price=250_000, stock=10, category_id=software.id),
        ])

        for number in range(5):
            db.session.add(Product(
                title=f"کابل {number}", price=1_000 * (number + 1) + 20_000,
                stock=3, category_id=hardware.id,
            ))

        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def product_id(app, title):
    with app.app_context():
        return Product.query.filter_by(title=title).one().id


def stock_of(app, title):
    with app.app_context():
        return Product.query.filter_by(title=title).one().stock


# ------------------------------------------------------------------ لیست

def test_list_is_paginated(client):
    page1 = client.get("/products/").get_data(as_text=True)
    page3 = client.get("/products/?page=3").get_data(as_text=True)

    assert page1.count("public-product-card") == 3
    assert "pagination" in page1
    assert "public-product-card" in page3


def test_list_page_beyond_range_does_not_crash(client):
    assert client.get("/products/?page=999").status_code == 200
    assert client.get("/products/?page=abc").status_code == 200


def test_search_by_title(client):
    html = client.get("/products/?q=آنتی").get_data(as_text=True)

    assert "آنتی‌ویروس" in html
    assert "کلید امنیتی" not in html


def test_search_treats_percent_literally(client):
    html = client.get("/products/?q=%25").get_data(as_text=True)

    assert "public-product-card" not in html
    assert "محصولی با این فیلترها پیدا نشد" in html


def test_filter_by_category_and_in_stock(app, client):
    with app.app_context():
        software_id = Category.query.filter_by(name="نرم‌افزار").one().id

    html = client.get(f"/products/?category={software_id}").get_data(as_text=True)
    assert "آنتی‌ویروس" in html
    assert "کلید امنیتی" not in html

    html = client.get("/products/?in_stock=1&q=مودم").get_data(as_text=True)
    assert "مودم قدیمی" not in html


def test_invalid_category_and_sort_are_ignored(client):
    assert client.get("/products/?category=abc&sort=hack").status_code == 200


def test_sort_by_price(client):
    html = client.get("/products/?sort=expensive").get_data(as_text=True)

    assert html.index("کلید امنیتی") < html.index("آنتی‌ویروس")


def test_price_is_formatted_in_rial(client):
    html = client.get("/products/?q=کلید").get_data(as_text=True)

    assert "500,000 ریال" in html


# ----------------------------------------------------------------- جزئیات

def test_detail_page(app, client):
    pid = product_id(app, "کلید امنیتی")
    html = client.get(f"/products/{pid}").get_data(as_text=True)

    assert "کلید امنیتی" in html
    assert "500,000 ریال" in html
    assert f"/shop/cart/add/{pid}" in html
    assert "محصولات مرتبط" in html


def test_detail_out_of_stock_has_no_add_form(app, client):
    pid = product_id(app, "مودم قدیمی")
    html = client.get(f"/products/{pid}").get_data(as_text=True)

    assert "ناموجود" in html
    assert f"/shop/cart/add/{pid}" not in html


def test_detail_missing_product_is_404(client):
    assert client.get("/products/99999").status_code == 404


def test_description_is_escaped(app, client):
    with app.app_context():
        category = Category.query.first()
        product = Product(
            title="xss", description="<script>alert(1)</script>",
            price=10_000, stock=1, category_id=category.id,
        )
        db.session.add(product)
        db.session.commit()
        pid = product.id

    html = client.get(f"/products/{pid}").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------------------- سبد

def test_add_to_cart_and_badge(app, client):
    pid = product_id(app, "کلید امنیتی")

    response = client.post(f"/shop/cart/add/{pid}", data={"quantity": "2"})
    assert response.status_code == 302

    html = client.get("/shop/cart").get_data(as_text=True)
    assert "کلید امنیتی" in html
    assert "1,000,000 ریال" in html
    assert 'class="cart-badge"' in html


def test_cart_quantity_is_capped_by_stock(app, client):
    pid = product_id(app, "کلید امنیتی")

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "99"})
    html = client.get("/shop/cart").get_data(as_text=True)

    assert 'value="5"' in html


def test_out_of_stock_cannot_be_added(app, client):
    pid = product_id(app, "مودم قدیمی")

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    html = client.get("/shop/cart").get_data(as_text=True)

    assert "سبد خرید شما خالی است" in html


def test_cart_remove(app, client):
    pid = product_id(app, "کلید امنیتی")

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    client.post(f"/shop/cart/remove/{pid}")

    assert "سبد خرید شما خالی است" in client.get("/shop/cart").get_data(as_text=True)


# ------------------------------------------------------------ ثبت و پرداخت

CUSTOMER = {
    "full_name": "علی رضایی",
    "phone": "۰۹۱۲۳۴۵۶۷۸۹",
    "email": "",
    "note": "",
}


def start_checkout(app, client, title="کلید امنیتی", quantity=2):
    pid = product_id(app, title)
    client.post(f"/shop/cart/add/{pid}", data={"quantity": str(quantity)})
    return client.post("/shop/checkout", data=CUSTOMER)


def test_checkout_requires_items(client):
    response = client.get("/shop/checkout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/shop/cart")


def test_checkout_rejects_bad_phone(app, client):
    pid = product_id(app, "کلید امنیتی")
    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})

    response = client.post(
        "/shop/checkout", data={**CUSTOMER, "phone": "123"}
    )

    assert response.status_code == 200
    assert "شمارهٔ موبایل معتبر نیست" in response.get_data(as_text=True)

    with app.app_context():
        assert Order.query.count() == 0


def test_minimum_payment_is_enforced(app, client):
    pid = product_id(app, "کابل 0")  # 21,000 ریال × 1 بالاتر از حداقل است
    with app.app_context():
        product = db.session.get(Product, pid)
        product.price = 5_000
        db.session.commit()

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    response = client.get("/shop/checkout")

    assert response.status_code == 302


def test_successful_payment_flow(app, client):
    response = start_checkout(app, client)

    assert response.status_code == 302
    assert "/shop/mock-pay/" in response.headers["Location"]

    # موجودی در لحظهٔ ثبت سفارش رزرو می‌شود
    assert stock_of(app, "کلید امنیتی") == 3

    response = client.post(response.headers["Location"], data={"result": "ok"})
    response = client.get(response.headers["Location"], follow_redirects=True)
    html = response.get_data(as_text=True)

    assert "پرداخت‌شده" in html

    with app.app_context():
        order = Order.query.one()

        assert order.status == OrderStatus.PAID
        assert order.total_rial == 1_000_000
        assert order.phone == "09123456789"
        assert order.ref_id

    assert stock_of(app, "کلید امنیتی") == 3
    assert "سبد خرید شما خالی است" in client.get("/shop/cart").get_data(as_text=True)


def test_cancelled_payment_restores_stock(app, client):
    response = start_checkout(app, client)
    assert stock_of(app, "کلید امنیتی") == 3

    response = client.post(response.headers["Location"], data={"result": "nok"})
    client.get(response.headers["Location"])

    with app.app_context():
        assert Order.query.one().status == OrderStatus.FAILED

    assert stock_of(app, "کلید امنیتی") == 5


def test_callback_replay_does_not_change_stock_twice(app, client):
    response = start_checkout(app, client)
    pay_url = response.headers["Location"]

    callback = client.post(pay_url, data={"result": "nok"}).headers["Location"]

    client.get(callback)
    client.get(callback)

    assert stock_of(app, "کلید امنیتی") == 5


def test_unpaid_callback_with_ok_status_is_not_trusted(app, client):
    response = start_checkout(app, client)
    authority = response.headers["Location"].rsplit("/", 1)[-1]

    # مشتری بدون پرداخت، آدرس بازگشت را با Status=OK صدا می‌زند
    client.get(f"/shop/payment/callback?Authority={authority}&Status=OK")

    with app.app_context():
        assert Order.query.one().status != OrderStatus.PAID


def test_callback_with_unknown_authority_is_404(client):
    response = client.get("/shop/payment/callback?Authority=nope&Status=OK")

    assert response.status_code == 404


def test_order_page_unknown_code_is_404(client):
    assert client.get("/shop/order/does-not-exist").status_code == 404


def test_order_page_hides_other_customers_behind_random_code(app, client):
    start_checkout(app, client)

    with app.app_context():
        code = Order.query.one().public_code

    assert len(code) >= 20
    assert client.get(f"/shop/order/{code}").status_code == 200
    assert client.get("/shop/order/1").status_code == 404


def test_mock_gateway_is_disabled_outside_debug(app):
    class ProdConfig(ShopTestConfig):
        TESTING = False
        DEBUG = False

    prod = create_app(ProdConfig)

    with prod.app_context():
        from app.modules.shop.gateways import GatewayError, get_gateway

        with pytest.raises(GatewayError):
            get_gateway()


# ------------------------------------------------------------------ مدیریت

@pytest.mark.parametrize("url", ["/shop/manage/orders", "/shop/manage/orders/1"])
def test_order_management_requires_login(client, url):
    response = client.get(url)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_navbar_links_to_cart(client):
    html = client.get("/").get_data(as_text=True)

    assert re.search(r'href="/shop/cart"', html)
