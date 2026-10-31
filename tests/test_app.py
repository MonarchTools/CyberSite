
import pytest

from app import create_app
from app.extensions import db
from app.modules.home.models import SiteSetting


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture()
def app():
    app = create_app(TestConfig)

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "CyberSite" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "url",
    [
        "/products/",
        "/blog/",
        "/admin/",
        "/contact/",
    ],
)
def test_module_pages(client, url):
    response = client.get(url)
    assert response.status_code == 200


def test_site_settings_created(app):
    with app.app_context():
        setting = db.session.get(SiteSetting, 1)

        assert setting is not None
        assert setting.site_name == "CyberSite"
