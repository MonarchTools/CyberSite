import pytest

from app import create_app
from app.extensions import db
from config import Config


class AboutConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app():
    app = create_app(AboutConfig)

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_about_page_has_social_links(client):
    response = client.get("/about")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="https://www.instagram.com/monarch_central"' in html
    assert 'href="https://t.me/sinagh83"' in html
    assert 'href="mailto:sina8200736@gmail.com"' in html
    # لینک‌های بیرونی بدون دسترسی به صفحهٔ ما باز می‌شوند
    assert html.count('target="_blank" rel="noopener noreferrer"') == 2


def test_about_is_in_navbar_and_marked_active(client):
    html = client.get("/about").get_data(as_text=True)

    assert 'href="/about" class="active"' in html
    assert 'href="/about"' in client.get("/").get_data(as_text=True)
    assert 'href="/" class="active"' in client.get("/").get_data(as_text=True)


def test_blog_link_is_active_on_blog_pages(client):
    assert 'href="/blog/" class="active"' in client.get("/blog/").get_data(as_text=True)


def test_about_ignores_unsafe_config(app):
    app.config["SOCIAL_INSTAGRAM_URL"] = "javascript:alert(1)"
    app.config["SOCIAL_TELEGRAM_URL"] = "http://insecure.example"
    app.config["PUBLIC_EMAIL"] = 'a@b.com" onclick="x'

    html = app.test_client().get("/about").get_data(as_text=True)

    assert "javascript:" not in html
    assert "insecure.example" not in html
    assert "onclick" not in html
