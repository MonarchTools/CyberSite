import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.products.models import Category, Product
from config import Config


PASSWORD = "a-very-long-password-123"


def make_app(monkeypatch, tmp_path, uri):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    class BackupConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = uri
        WTF_CSRF_ENABLED = False
        PAYMENT_GATEWAY = "mock"

    app = create_app(BackupConfig)
    app.instance_path = str(tmp_path)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        db.session.add_all([admin, Category(name="سخت‌افزار")])
        db.session.commit()

    return app


@pytest.fixture()
def app(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, f"sqlite:///{tmp_path / 'site.db'}")
    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def admin(app):
    c = app.test_client()
    c.get("/admin/captcha.png")
    c.post("/admin/login",
           data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})
    return c


def add_product(app, title):
    with app.app_context():
        db.session.add(Product(title=title, price=100_000, stock=1, category_id=1))
        db.session.commit()


def titles(app):
    with app.app_context():
        return sorted(p.title for p in Product.query.all())


def upload_file(app, name, data):
    path = Path(app.instance_path) / "uploads" / "files" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def take_backup(admin):
    response = admin.post("/admin/backup/download")
    assert response.status_code == 200
    return response.get_data()


def restore(admin, data, *, password=PASSWORD, confirm=True, name="b.zip"):
    form = {"password": password, "backup_file": (io.BytesIO(data), name)}

    if confirm:
        form["confirm"] = "y"

    return admin.post("/admin/backup/restore", data=form,
                      content_type="multipart/form-data")


def test_pages_require_admin_login(app):
    client = app.test_client()

    assert client.get("/admin/backup/").status_code == 302
    assert client.post("/admin/backup/download").status_code == 302
    assert client.post("/admin/backup/restore").status_code == 302


def test_backup_zip_contains_db_uploads_and_manifest(app, admin):
    add_product(app, "کلید امنیتی")
    upload_file(app, "book.zip", b"PK-content")

    response = admin.post("/admin/backup/download")

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]

    archive = zipfile.ZipFile(io.BytesIO(response.get_data()))
    names = set(archive.namelist())
    assert {"manifest.json", "database.sqlite3", "uploads/files/book.zip"} <= names
    assert archive.read("uploads/files/book.zip") == b"PK-content"

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["app"] == "cybersite" and manifest["upload_files"] == 1

    snapshot = Path(app.instance_path) / "snap.db"
    snapshot.write_bytes(archive.read("database.sqlite3"))
    conn = sqlite3.connect(snapshot)
    assert conn.execute("select title from products").fetchall() == [("کلید امنیتی",)]
    conn.close()

    # فایل .env یا کلیدها داخل پشتیبان نیست
    assert not any("env" in n.lower() for n in names)


def test_stale_warning_disappears_after_backup(app, admin):
    assert "هنوز هیچ پشتیبانی نگرفته‌اید" in admin.get("/admin/backup/").get_data(as_text=True)
    assert "پشتیبان تازه‌ای از سایت ندارید" in admin.get("/admin/").get_data(as_text=True)

    take_backup(admin)

    assert "هنوز هیچ پشتیبانی" not in admin.get("/admin/backup/").get_data(as_text=True)
    assert "پشتیبان تازه‌ای از سایت ندارید" not in admin.get("/admin/").get_data(as_text=True)


def test_restore_roundtrip(app, admin):
    add_product(app, "قدیمی")
    keep = upload_file(app, "keep.zip", b"original")
    data = take_backup(admin)

    add_product(app, "جدید")
    keep.write_bytes(b"changed")
    upload_file(app, "extra.zip", b"extra")

    response = restore(admin, data)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]

    assert titles(app) == ["قدیمی"]
    assert keep.read_bytes() == b"original"
    assert not (Path(app.instance_path) / "uploads" / "files" / "extra.zip").exists()

    # نسخهٔ ایمنی از وضعیت قبل از بازگردانی ساخته شد
    safety = list((Path(app.instance_path) / "backups").glob("before-restore-*.zip"))
    assert len(safety) == 1
    assert "database.sqlite3" in zipfile.ZipFile(safety[0]).namelist()

    # مدیر خارج شده و سایت هنوز کار می‌کند
    assert admin.get("/admin/backup/").status_code == 302
    assert app.test_client().get("/products/").status_code == 200


def test_restore_requires_password_and_confirmation(app, admin):
    add_product(app, "قدیمی")
    data = take_backup(admin)
    add_product(app, "جدید")

    restore(admin, data, password="wrong-password")
    restore(admin, data, confirm=False)

    assert titles(app) == ["جدید", "قدیمی"]


def test_restore_rejects_bad_files_and_changes_nothing(app, admin):
    add_product(app, "قدیمی")

    assert restore(admin, b"not a zip").status_code == 302

    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", '{"app":"cybersite","format":1}')
        z.writestr("database.sqlite3", b"x")
        z.writestr("uploads/../../evil.txt", b"x")
    restore(admin, evil.getvalue())

    foreign = io.BytesIO()
    with zipfile.ZipFile(foreign, "w") as z:
        z.writestr("manifest.json", '{"app":"other","format":1}')
        z.writestr("database.sqlite3", b"x")
    restore(admin, foreign.getvalue())

    assert titles(app) == ["قدیمی"]
    assert not (Path(app.instance_path).parent / "evil.txt").exists()
    assert admin.get("/admin/backup/").status_code == 200     # هنوز وارد است


def test_in_memory_database_is_reported_as_unsupported(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, "sqlite://")
    client = app.test_client()
    client.get("/admin/captcha.png")
    client.post("/admin/login",
                data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"})

    assert "فقط برای دیتابیس SQLite" in client.get("/admin/backup/").get_data(as_text=True)
    assert client.post("/admin/backup/download").status_code == 302
