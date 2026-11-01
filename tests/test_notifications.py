import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.products.models import Category, Product
from app.modules.shop.models import Order
from app import notifications
from config import Config


PASSWORD = "a-very-long-password-123"

CONTACT = {
    "name": "علی رضایی",
    "email": "ali@example.com",
    "phone": "",
    "subject": "سلام",
    "message": "این یک پیام آزمایشی برای بررسی ایمیل مدیر است.",
    "website": "",
    "captcha": "ABCDE",
}

CUSTOMER = {
    "full_name": "سارا احمدی",
    "phone": "09123456789",
    "email": "sara@example.com",
    "note": "",
}


class MailConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"
    MAIL_SERVER = "smtp.example.test"
    MAIL_FROM = "shop@example.test"
    ADMIN_NOTIFY_EMAIL = "owner@example.test"
    MAIL_ASYNC = False
    SITE_URL = "https://shop.example.test"


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "_send_smtp", lambda settings, message: sent.append(message))
    return sent


@pytest.fixture()
def app(monkeypatch, outbox):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(MailConfig)

    with app.app_context():
        category = Category(name="سخت‌افزار")
        db.session.add(category)
        db.session.flush()
        db.session.add(Product(title="کلید امنیتی", price=500_000, stock=5,
                               category_id=category.id))
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def send_contact(client, **overrides):
    client.get("/contact/captcha.png")
    return client.post("/contact/", data={**CONTACT, **overrides})


def pay(app, client, **customer):
    with app.app_context():
        pid = Product.query.one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "2"})
    response = client.post("/shop/checkout", data={**CUSTOMER, **customer})
    return client.post(response.headers["Location"], data={"result": "ok"})


def admin_client(app):
    admin = app.test_client()
    admin.get("/admin/captcha.png")
    admin.post("/admin/login",
               data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    return admin


# --------------------------------------------------------------- پیام تماس

def test_contact_message_emails_admin_with_reply_to(app, outbox):
    client = app.test_client()

    assert send_contact(client).status_code == 302
    assert len(outbox) == 1

    mail = outbox[0]
    assert mail["To"] == "owner@example.test"
    assert mail["From"] == "shop@example.test"
    assert mail["Reply-To"] == "ali@example.com"
    assert "علی رضایی" in mail["Subject"]
    assert "این یک پیام آزمایشی" in mail.get_content()
    assert "https://shop.example.test/contact/manage" in mail.get_content()


def test_rejected_or_bot_messages_send_nothing(app, outbox):
    client = app.test_client()

    send_contact(client, captcha="ZZZZZ")
    send_contact(client, website="http://spam.example")

    assert outbox == []


def test_header_injection_is_neutralised(app, outbox):
    client = app.test_client()

    send_contact(client, name="سارا\r\nBcc: evil@example.com")

    for mail in outbox:
        assert mail["Bcc"] is None
        assert "\n" not in mail["Subject"] and "\r" not in mail["Subject"]


# ------------------------------------------------------------------ سفارش

def test_paid_order_emails_admin_and_customer_once(app, outbox):
    client = app.test_client()
    pay(app, client)

    recipients = sorted(mail["To"] for mail in outbox)
    assert recipients == ["owner@example.test", "sara@example.com"]

    customer_mail = next(m for m in outbox if m["To"] == "sara@example.com")
    body = customer_mail.get_content()
    assert "کلید امنیتی" in body

    with app.app_context():
        code = Order.query.one().public_code

    assert f"https://shop.example.test/shop/order/{code}" in body

    # بازگشت تکراری از درگاه دوباره ایمیل نمی‌فرستد
    with app.app_context():
        authority = Order.query.one().authority

    client.get(f"/shop/payment/callback?Authority={authority}&Status=OK")
    assert len(outbox) == 2


def test_unpaid_or_failed_order_sends_nothing(app, outbox):
    client = app.test_client()

    with app.app_context():
        pid = Product.query.one().id

    client.post(f"/shop/cart/add/{pid}", data={"quantity": "1"})
    response = client.post("/shop/checkout", data=CUSTOMER)
    client.post(response.headers["Location"], data={"result": "cancel"})

    assert outbox == []


def test_order_without_customer_email_only_notifies_admin(app, outbox):
    pay(app, app.test_client(), email="")

    assert [mail["To"] for mail in outbox] == ["owner@example.test"]


def test_shipping_emails_customer_with_tracking_once(app, outbox):
    pay(app, app.test_client())
    outbox.clear()

    admin = admin_client(app)
    data = {"fulfillment": "shipped", "tracking_code": "TRK-77"}

    admin.post("/shop/manage/orders/1/fulfillment", data=data)

    assert len(outbox) == 1
    assert outbox[0]["To"] == "sara@example.com"
    assert "TRK-77" in outbox[0].get_content()

    # ذخیرهٔ دوباره بدون تغییر مرحله ایمیل تکراری نمی‌فرستد
    admin.post("/shop/manage/orders/1/fulfillment", data=data)
    assert len(outbox) == 1

    # مرحلهٔ «در حال آماده‌سازی» ایمیل ندارد
    admin.post("/shop/manage/orders/1/fulfillment", data={"fulfillment": "processing"})
    assert len(outbox) == 1

    admin.post("/shop/manage/orders/1/fulfillment", data={"fulfillment": "delivered"})
    assert len(outbox) == 2
    assert "تحویل" in outbox[1]["Subject"]


# ------------------------------------------------------------ تنظیمات و خطا

def test_nothing_is_sent_when_mail_is_not_configured(monkeypatch, outbox):
    class Off(MailConfig):
        MAIL_SERVER = ""

    app = create_app(Off)
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    client = app.test_client()
    assert send_contact(client).status_code == 302
    assert outbox == []

    with app.app_context():
        db.drop_all()


def test_smtp_failure_never_breaks_the_request(app, monkeypatch):
    def boom(settings, message):
        raise OSError("smtp down")

    monkeypatch.setattr(notifications, "_send_smtp", boom)

    client = app.test_client()

    assert send_contact(client).status_code == 302

    response = pay(app, client)
    assert response.status_code == 302

    with app.app_context():
        assert Order.query.one().status == "paid"


def test_send_mail_rejects_bad_recipient(app, outbox):
    with app.app_context():
        assert notifications.send_mail("not-an-address", "s", "b") is False
        assert notifications.send_mail("a@b.com\r\nBcc: x@y.com", "s", "b") is False

    assert outbox == []
