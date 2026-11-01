import re
import time
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin, LoginAttempt
from config import Config


PASSWORD = "a-very-long-password-123"


class SecurityTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    LOGIN_MAX_ATTEMPTS = 3
    LOGIN_LOCK_MINUTES = 10


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(SecurityTestConfig)

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


def attempt(client, password=PASSWORD, captcha="ABCDE", **kwargs):
    client.get("/admin/captcha.png", **kwargs)

    return client.post(
        "/admin/login",
        data={
            "username": "owner",
            "password": password,
            "captcha": captcha,
        },
        **kwargs,
    )


def lock_out(client):
    for _ in range(2):
        assert attempt(client, password="wrong-password-1").status_code == 200

    return attempt(client, password="wrong-password-1")


# ------------------------------------------------------------- قفل ورود

def test_lock_after_repeated_failures(client):
    response = lock_out(client)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_correct_password_rejected_while_locked(client):
    lock_out(client)

    response = attempt(client)

    assert response.status_code == 429
    assert client.get("/admin/").status_code == 302


def test_locked_page_hides_form_and_captcha(client):
    lock_out(client)

    response = client.get("/admin/login")
    html = response.get_data(as_text=True)

    assert response.status_code == 429
    assert 'name="password"' not in html
    assert client.get("/admin/captcha.png").status_code == 429


def test_lock_expires(app, client):
    lock_out(client)

    with app.app_context():
        row = LoginAttempt.query.one()
        row.locked_until = time.time() - 1
        db.session.commit()

    response = attempt(client)

    assert response.status_code == 302
    assert client.get("/admin/").status_code == 200


def test_success_clears_failed_attempts(app, client):
    attempt(client, password="wrong-password-1")
    attempt(client, password="wrong-password-1")

    assert attempt(client).status_code == 302

    with app.app_context():
        assert LoginAttempt.query.count() == 0


def test_wrong_captcha_counts_as_failure(client):
    for _ in range(2):
        assert attempt(client, captcha="ZZZZZ").status_code == 200

    assert attempt(client, captcha="ZZZZZ").status_code == 429


def test_other_ip_is_not_locked(client):
    lock_out(client)

    other = {"environ_base": {"REMOTE_ADDR": "10.9.9.9"}}

    assert client.get("/admin/login", **other).status_code == 200
    assert attempt(client, **other).status_code == 302


def test_stale_failures_are_forgotten(app, client):
    attempt(client, password="wrong-password-1")
    attempt(client, password="wrong-password-1")

    with app.app_context():
        row = LoginAttempt.query.one()
        row.updated_at = time.time() - 3600
        db.session.commit()

    # شمارندهٔ قدیمی از نو شروع می‌شود، پس این تلاش قفل نمی‌کند
    assert attempt(client, password="wrong-password-1").status_code == 200


def test_unknown_user_gets_same_generic_message(client):
    client.get("/admin/captcha.png")
    response = client.post(
        "/admin/login",
        data={"username": "nobody", "password": PASSWORD, "captcha": "ABCDE"},
    )

    assert response.status_code == 200
    assert "نام کاربری یا رمز عبور اشتباه است" in response.get_data(as_text=True)


# ------------------------------------------------------------------ نشست

def test_admin_session_cookie_is_persistent_with_expiry(client):
    response = attempt(client)

    cookies = " ".join(response.headers.getlist("Set-Cookie"))

    assert "Expires=" in cookies
    assert "HttpOnly" in cookies
    assert "SameSite=Lax" in cookies


def test_logout_clears_session(client):
    attempt(client)

    assert client.get("/admin/").status_code == 200

    client.post("/admin/logout")

    assert client.get("/admin/").status_code == 302


# ------------------------------------------------------------------ هدرها

def test_security_headers_on_public_page(client):
    response = client.get("/")
    headers = response.headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "same-origin"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in headers


@pytest.mark.parametrize(
    "url",
    ["/admin/login", "/shop/cart", "/shop/checkout", "/products/manage"],
)
def test_private_pages_are_not_cacheable(client, url):
    response = client.get(url)

    assert "no-store" in response.headers["Cache-Control"]


def test_hsts_only_when_cookie_is_secure():
    class SecureConfig(SecurityTestConfig):
        SESSION_COOKIE_SECURE = True

    secure_app = create_app(SecureConfig)

    response = secure_app.test_client().get("/")

    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_templates_have_no_inline_scripts_or_styles():
    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    handler = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)

    for path in templates.rglob("*.html"):
        text = path.read_text(encoding="utf-8-sig")

        assert not handler.search(text), f"inline handler in {path}"
        assert "<style" not in text, f"inline <style> in {path}"
        assert not re.search(r"<script(?![^>]*\ssrc=)", text), (
            f"inline <script> in {path}"
        )


# ------------------------------------------------------------- SECRET_KEY

class ProductionConfig(SecurityTestConfig):
    TESTING = False
    DEBUG = False


@pytest.mark.parametrize(
    "key",
    [None, "", "short", "your-secret-key-here", "change-this-secret-key"],
)
def test_production_refuses_weak_secret_key(key):
    class Weak(ProductionConfig):
        SECRET_KEY = key

    with pytest.raises(RuntimeError):
        create_app(Weak)


def test_production_accepts_strong_secret_key():
    class Strong(ProductionConfig):
        SECRET_KEY = "k" * 48

    assert create_app(Strong).config["SECRET_KEY"] == "k" * 48


def test_debug_without_key_gets_temporary_key():
    class Dev(ProductionConfig):
        DEBUG = True
        SECRET_KEY = None

    app = create_app(Dev)

    assert len(app.config["SECRET_KEY"]) == 64
