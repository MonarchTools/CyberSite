import re

import pytest

from app import create_app, notifications
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.customers import reset as reset_module
from app.modules.customers.models import Customer
from config import Config


EMAIL = "buyer@example.test"
OLD = "old-password-123"
NEW = "brand-new-password-9"


class ResetConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    PAYMENT_GATEWAY = "mock"
    MAIL_SERVER = "smtp.example.test"
    MAIL_FROM = "shop@example.test"
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
    app = create_app(ResetConfig)

    with app.app_context():
        c = Customer(email=EMAIL, full_name="خریدار")
        c.set_password(OLD)
        db.session.add(c)
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def ask(client, email=EMAIL, captcha="ABCDE"):
    client.get("/account/captcha.png")
    return client.post("/account/forgot", data={"email": email, "captcha": captcha})


def link_from(outbox):
    return re.search(r"https://shop\.example\.test(/account/reset/\S+)",
                     outbox[-1].get_content()).group(1)


def test_request_sends_link_and_login_page_links_to_forgot(client, outbox):
    assert "/account/forgot" in client.get("/account/login").get_data(as_text=True)

    r = ask(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/login")
    assert len(outbox) == 1
    assert outbox[0]["To"] == EMAIL
    assert "/account/reset/" in outbox[0].get_content()


def test_unknown_email_gets_same_answer_and_no_mail(client, outbox):
    r = ask(client, email="nobody@example.test")

    assert r.status_code == 302 and r.headers["Location"].endswith("/account/login")
    assert outbox == []


def test_wrong_captcha_sends_nothing(client, outbox):
    r = ask(client, captcha="ZZZZZ")

    assert r.status_code == 200
    assert outbox == []


def test_inactive_customer_gets_no_mail(app, client, outbox):
    with app.app_context():
        Customer.query.one().is_active = False
        db.session.commit()

    ask(client)
    assert outbox == []


def test_reset_flow_changes_password_and_link_is_single_use(app, client, outbox):
    ask(client)
    path = link_from(outbox)

    page = client.get(path)
    assert page.status_code == 200
    assert page.headers["Referrer-Policy"] == "no-referrer"

    r = client.post(path, data={"password": NEW, "password2": NEW})
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/login")

    with app.app_context():
        c = Customer.query.one()
        assert c.check_password(NEW)
        assert not c.check_password(OLD)

    # همان لینک دوباره کار نمی‌کند
    again = client.post(path, data={"password": "another-pass-77", "password2": "another-pass-77"})
    assert again.status_code == 302 and again.headers["Location"].endswith("/account/forgot")

    with app.app_context():
        assert Customer.query.one().check_password(NEW)


def test_new_password_lets_customer_log_in(client, outbox):
    ask(client)
    client.post(link_from(outbox), data={"password": NEW, "password2": NEW})

    client.get("/account/captcha.png")
    r = client.post("/account/login", data={"email": EMAIL, "password": NEW, "captcha": "ABCDE"})
    assert r.status_code == 302
    assert "/account/login" not in r.headers["Location"]


def test_mismatched_or_short_password_rejected(app, client, outbox):
    ask(client)
    path = link_from(outbox)

    assert client.post(path, data={"password": NEW, "password2": "different-1234"}).status_code == 200
    assert client.post(path, data={"password": "short", "password2": "short"}).status_code == 200

    with app.app_context():
        assert Customer.query.one().check_password(OLD)


def test_tampered_token_rejected(client):
    r = client.get("/account/reset/not-a-real-token")
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/forgot")


def test_expired_token_rejected(app, client, outbox):
    ask(client)
    path = link_from(outbox)
    app.config["PASSWORD_RESET_MINUTES"] = 0

    import time
    time.sleep(1.1)

    r = client.get(path)
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/forgot")


def test_token_from_other_purpose_rejected(app, client):
    from itsdangerous import URLSafeTimedSerializer

    with app.app_context():
        cid = Customer.query.one().id

    forged = URLSafeTimedSerializer("test-secret", salt="something-else").dumps({"id": cid, "fp": "x"})
    r = client.get(f"/account/reset/{forged}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/forgot")


def test_requests_are_throttled(client, outbox):
    codes = [ask(client).status_code for _ in range(12)]

    assert 429 in codes
    assert len(outbox) < 12
