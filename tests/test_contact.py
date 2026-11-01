import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.contact.models import ContactMessage
from config import Config


PASSWORD = "a-very-long-password-123"

VALID = {
    "name": "علی رضایی",
    "email": "ali@example.com",
    "phone": "",
    "subject": "سلام",
    "message": "این یک پیام آزمایشی برای بررسی فرم تماس است.",
    "website": "",
}


class ContactTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    CONTACT_MAX_PER_HOUR = 3


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(ContactTestConfig)

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


def send(client, captcha="ABCDE", fetch_captcha=True, **overrides):
    if fetch_captcha:
        client.get("/contact/captcha.png")

    data = {**VALID, "captcha": captcha, **overrides}

    return client.post("/contact/", data=data)


def message_count(app):
    with app.app_context():
        return ContactMessage.query.count()


def admin_login(client):
    client.get("/admin/captcha.png")

    return client.post(
        "/admin/login",
        data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"},
    )


# ------------------------------------------------------------- فرم عمومی

def test_contact_page_has_form_and_captcha(client):
    response = client.get("/contact/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="message"' in html
    assert "/contact/captcha.png" in html


def test_captcha_image(client):
    response = client.get("/contact/captcha.png")

    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")
    assert "no-store" in response.headers["Cache-Control"]


def test_valid_message_is_saved(app, client):
    response = send(client)

    assert response.status_code == 302

    with app.app_context():
        saved = ContactMessage.query.one()

        assert saved.name == "علی رضایی"
        assert saved.email == "ali@example.com"
        assert saved.is_read is False
        assert saved.phone is None
        # IP خام ذخیره نمی‌شود
        assert "127.0.0.1" not in saved.ip_hash
        assert len(saved.ip_hash) == 64


def test_wrong_captcha_is_rejected(app, client):
    response = send(client, captcha="ZZZZZ")

    assert response.status_code == 200
    assert "کد امنیتی" in response.get_data(as_text=True)
    assert message_count(app) == 0


def test_captcha_is_single_use(app, client):
    assert send(client).status_code == 302

    # همان پاسخ بدون گرفتن تصویر تازه دیگر معتبر نیست
    response = send(client, fetch_captcha=False)

    assert response.status_code == 200
    assert message_count(app) == 1


def test_honeypot_silently_drops_bots(app, client):
    response = send(client, website="http://spam.example")

    assert response.status_code == 302
    assert message_count(app) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"email": "a@b.c?cc=evil@x.com"},
        {"message": "کوتاه"},
        {"name": ""},
        {"phone": "123"},
        {"message": "ا" * 2001},
    ],
)
def test_invalid_input_is_rejected(app, client, overrides):
    response = send(client, **overrides)

    assert response.status_code == 200
    assert message_count(app) == 0


def test_persian_phone_digits_are_normalised(app, client):
    send(client, phone="۰۹۱۲۳۴۵۶۷۸۹")

    with app.app_context():
        assert ContactMessage.query.one().phone == "09123456789"


def test_rate_limit_per_ip(app, client):
    for _ in range(3):
        assert send(client).status_code == 302

    response = send(client)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert message_count(app) == 3


def test_other_ip_is_not_rate_limited(app, client):
    for _ in range(3):
        send(client)

    other = client.application.test_client()
    other.get("/contact/captcha.png", environ_base={"REMOTE_ADDR": "10.1.1.1"})
    response = other.post(
        "/contact/",
        data={**VALID, "captcha": "ABCDE"},
        environ_base={"REMOTE_ADDR": "10.1.1.1"},
    )

    assert response.status_code == 302
    assert message_count(app) == 4


def test_captchas_of_different_forms_do_not_clash(client):
    client.get("/admin/captcha.png")
    client.get("/contact/captcha.png")

    with client.session_transaction() as session:
        assert "captcha_token" in session
        assert "captcha_token_contact" in session


def test_login_captcha_does_not_work_for_contact_form(app, client):
    client.get("/admin/captcha.png")  # فقط چالش ورود وجود دارد

    response = send(client, fetch_captcha=False)

    assert response.status_code == 200
    assert message_count(app) == 0


# --------------------------------------------------------------- ادمین

@pytest.mark.parametrize(
    "url", ["/contact/manage", "/contact/manage/1"]
)
def test_inbox_requires_login(client, url):
    response = client.get(url)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_delete_requires_login_and_post(app, client):
    send(client)

    assert client.post("/contact/manage/1/delete").status_code == 302
    assert message_count(app) == 1

    admin_login(client)

    assert client.get("/contact/manage/1/delete").status_code == 405
    assert message_count(app) == 1


def test_inbox_list_detail_and_read_flag(app, client):
    send(client)
    admin_login(client)

    dashboard = client.get("/admin/").get_data(as_text=True)
    assert 'class="card-badge">1<' in dashboard

    listing = client.get("/contact/manage").get_data(as_text=True)
    assert "علی رضایی" in listing
    assert "جدید" in listing

    detail = client.get("/contact/manage/1")
    assert detail.status_code == 200
    assert "این یک پیام آزمایشی" in detail.get_data(as_text=True)

    with app.app_context():
        assert ContactMessage.query.one().is_read is True

    assert "card-badge" not in client.get("/admin/").get_data(as_text=True)

    unread = client.get("/contact/manage?filter=unread").get_data(as_text=True)
    assert "علی رضایی" not in unread


def test_message_content_is_escaped(client):
    send(client, message="<script>alert(1)</script> متن طولانی برای تست", name="<b>x</b>x")
    admin_login(client)

    html = client.get("/contact/manage/1").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>x</b>" not in html


def test_admin_can_delete_message(app, client):
    send(client)
    admin_login(client)

    response = client.post("/contact/manage/1/delete")

    assert response.status_code == 302
    assert message_count(app) == 0
    assert client.get("/contact/manage/1").status_code == 404


def test_inbox_pages_are_not_cacheable(client):
    admin_login(client)

    response = client.get("/contact/manage")

    assert "no-store" in response.headers["Cache-Control"]
