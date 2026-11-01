import time

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin, CaptchaChallenge


PASSWORD = "a-very-long-password-123"


class CaptchaTestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(monkeypatch):
    # متن کپچا را ثابت می‌کنیم تا تست بتواند پاسخ درست را بفرستد
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(CaptchaTestConfig)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, captcha="ABCDE", password=PASSWORD):
    return client.post(
        "/admin/login",
        data={
            "username": "owner",
            "password": password,
            "captcha": captcha,
        },
    )


def test_captcha_image_is_png_and_not_cached(client):
    response = client.get("/admin/captcha.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")
    assert "no-store" in response.headers["Cache-Control"]


def test_login_page_contains_captcha(client):
    html = client.get("/admin/login").get_data(as_text=True)

    assert "/admin/captcha.png" in html
    assert 'name="captcha"' in html


def test_login_succeeds_with_correct_captcha(client):
    client.get("/admin/captcha.png")

    response = login(client)

    assert response.status_code == 302
    assert client.get("/admin/").status_code == 200


def test_wrong_captcha_rejected_even_with_correct_password(client):
    client.get("/admin/captcha.png")

    response = login(client, captcha="ZZZZZ")

    assert response.status_code == 200
    assert "کد امنیتی" in response.get_data(as_text=True)
    assert client.get("/admin/").status_code == 302


def test_login_without_requesting_captcha_fails(client):
    assert login(client).status_code == 200
    assert client.get("/admin/").status_code == 302


def test_captcha_is_single_use(client):
    client.get("/admin/captcha.png")

    # اولین تلاش با رمز اشتباه، چالش را مصرف می‌کند
    login(client, password="wrong-password-123")

    # همان پاسخ درست بدون چالش تازه دیگر پذیرفته نمی‌شود
    response = login(client)

    assert response.status_code == 200
    assert client.get("/admin/").status_code == 302


def test_new_image_invalidates_previous_challenge(app, client):
    client.get("/admin/captcha.png")
    client.get("/admin/captcha.png")

    with app.app_context():
        assert CaptchaChallenge.query.count() == 1


def test_expired_captcha_rejected(app, client):
    client.get("/admin/captcha.png")

    with app.app_context():
        challenge = CaptchaChallenge.query.one()
        challenge.expires_at = time.time() - 1
        db.session.commit()

    assert login(client).status_code == 200
    assert client.get("/admin/").status_code == 302


def test_answer_is_not_stored_in_plaintext(app, client):
    client.get("/admin/captcha.png")

    with app.app_context():
        challenge = CaptchaChallenge.query.one()

        assert "ABCDE" not in challenge.answer_hash
        assert "ABCDE" not in challenge.token


def test_answer_is_case_and_digit_insensitive(client, monkeypatch):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "AB234")
    client.get("/admin/captcha.png")

    assert login(client, captcha=" ab۲۳۴ ").status_code == 302
