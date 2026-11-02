import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.content.models import SiteContent
from app.modules.content.registry import FIELDS, SECTIONS, default_for
from config import Config


PASSWORD = "a-very-long-password-123"


class ContentConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(ContentConfig)

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


@pytest.fixture()
def admin(app):
    c = app.test_client()
    c.get("/admin/captcha.png")
    c.post("/admin/login",
           data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    return c


def save(admin, **values):
    return admin.post("/content/manage", data=values)


def stored(app, key):
    with app.app_context():
        row = db.session.get(SiteContent, key)
        return row.value if row else None


def test_registry_keys_are_unique_and_defaults_are_valid(app):
    keys = [f["key"] for _, fields in SECTIONS for f in fields]

    assert len(keys) == len(set(keys))

    with app.app_context():
        for field in FIELDS.values():
            assert len(default_for(field, app.config)) <= field["max"]


def test_pages_show_defaults_when_nothing_is_saved(client):
    home = client.get("/").get_data(as_text=True)

    assert "دنیای من در" in home and "فضای سایبری" in home
    assert "مشاهده فروشگاه" in home

    about = client.get("/about").get_data(as_text=True)

    assert "درباره من" in about
    assert "@monarch_central" in about and "@sinagh83" in about


def test_editor_requires_login_and_is_not_cacheable(client, admin):
    response = client.get("/content/manage")

    assert response.status_code == 302 and "/admin/login" in response.headers["Location"]
    assert client.post("/content/manage", data={"home_badge": "x"}).status_code == 302

    page = admin.get("/content/manage")

    assert page.status_code == 200
    assert "no-store" in page.headers["Cache-Control"]
    assert 'name="home_title_accent"' in page.get_data(as_text=True)


def test_saved_text_appears_on_home_and_about(app, admin, client):
    save(admin, home_title_accent="دنیای دیجیتال", about_title="دربارهٔ سینا",
         about_intro="خط اول\nخط دوم")

    home = client.get("/").get_data(as_text=True)
    about = client.get("/about").get_data(as_text=True)

    assert "دنیای دیجیتال" in home
    assert "فضای سایبری" not in home
    assert "دربارهٔ سینا" in about
    assert '<p class="about-text">خط اول\nخط دوم</p>' in about


def test_empty_or_default_value_returns_to_default_and_removes_row(app, admin, client):
    save(admin, home_badge="نشان تازه")
    assert stored(app, "home_badge") == "نشان تازه"

    save(admin, home_badge="")
    assert stored(app, "home_badge") is None
    assert "PERSONAL CYBER PLATFORM" in client.get("/").get_data(as_text=True)

    save(admin, home_badge="PERSONAL CYBER PLATFORM")
    assert stored(app, "home_badge") is None


def test_html_is_escaped_never_executed(app, admin, client):
    save(admin, home_title_accent="<script>alert(1)</script>",
         about_intro='"><img src=x onerror=alert(1)>')

    home = client.get("/").get_data(as_text=True)
    about = client.get("/about").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in home
    assert "&lt;script&gt;" in home
    assert "<img src=x" not in about


@pytest.mark.parametrize("key,value", [
    ("home_badge", "ا" * 41),
    ("home_description", "ا" * 301),
    ("instagram_url", "javascript:alert(1)"),
    ("instagram_url", "http://insecure.example"),
    ("telegram_url", "https://t.me/a b"),
    ("public_email", "not-an-email"),
    ("public_email", 'a@b.com" onclick="x'),
])
def test_invalid_values_are_rejected_and_nothing_is_saved(app, admin, key, value):
    response = save(admin, home_title_accent="ذخیره نشود", **{key: value})

    assert response.status_code == 400
    assert stored(app, key) is None
    assert stored(app, "home_title_accent") is None


def test_unknown_keys_are_ignored(app, admin):
    save(admin, evil_key="x", **{"__class__": "y"})

    with app.app_context():
        assert SiteContent.query.count() == 0


def test_social_links_come_from_content_and_derive_handles(app, admin, client):
    save(admin, instagram_url="https://www.instagram.com/new_account/",
         telegram_url="https://t.me/newuser", public_email="me@example.com")

    html = client.get("/about").get_data(as_text=True)

    assert 'href="https://www.instagram.com/new_account/"' in html
    assert "@new_account" in html
    assert 'href="https://t.me/newuser"' in html and "@newuser" in html
    assert 'href="mailto:me@example.com"' in html


def test_tampered_database_value_is_not_rendered_as_link(app, client):
    with app.app_context():
        db.session.add(SiteContent(key="instagram_url", value="javascript:alert(1)"))
        db.session.commit()

    html = client.get("/about").get_data(as_text=True)

    assert "javascript:" not in html


def test_dashboard_links_to_editor(admin):
    assert "/content/manage" in admin.get("/admin/").get_data(as_text=True)
