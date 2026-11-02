import io
import re
from pathlib import Path

import pytest
from PIL import Image

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.slides.models import HomeSlide, is_safe_link
from config import Config


PASSWORD = "a-very-long-password-123"

# سرآیند حداقلی معتبر: MP4 با ftyp و WEBM با EBML
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 2000
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 2000


class SlideConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SLIDE_VIDEO_MAX_BYTES = 50_000


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(SlideConfig)
    app.instance_path = str(tmp_path)

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


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 80, 20)).save(buffer, "PNG")
    return buffer.getvalue()


def upload(data, name="x.png"):
    return (io.BytesIO(data), name)


def stored(app):
    folder = Path(app.instance_path) / "uploads" / "slides"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def create(admin, media, title="پروژهٔ نمونه", **extra):
    return admin.post(
        "/slides/create",
        data={"title": title, "caption": "", "link_url": "", "is_active": "y",
              "media": media, **extra},
        content_type="multipart/form-data",
    )


def rows(app):
    with app.app_context():
        return [(s.title, s.media_type, s.position, s.is_active)
                for s in HomeSlide.query.order_by(HomeSlide.position).all()]


# ------------------------------------------------------------- لینک امن

@pytest.mark.parametrize("url", ["/blog/", "/products/1", "https://example.com/a?b=1"])
def test_safe_links(url):
    assert is_safe_link(url)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,x", "http://insecure.example",
    "//evil.example", "/a b", "/a\\b", 'https://x.test/"onmouseover="x', "https://", "",
])
def test_unsafe_links(url):
    assert not is_safe_link(url)


# --------------------------------------------------------------- مدیریت

@pytest.mark.parametrize("url", ["/slides/manage", "/slides/create", "/slides/edit/1"])
def test_slide_admin_requires_login(client, url):
    response = client.get(url)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_mutations_require_login_and_post(app, client, admin):
    create(admin, upload(png()))

    for url in ("/slides/delete/1", "/slides/toggle/1", "/slides/move/1/down"):
        response = client.post(url)
        assert response.status_code == 302 and "/admin/login" in response.headers["Location"]
        assert admin.get(url).status_code == 405

    assert len(rows(app)) == 1


def test_image_slide_is_saved_as_clean_webp_and_shown_on_home(app, admin, client):
    assert "home-slider" not in client.get("/").get_data(as_text=True)

    response = create(admin, upload(png()), caption="توضیح", link_url="/blog/")

    assert response.status_code == 302
    assert rows(app) == [("پروژهٔ نمونه", "image", 0, True)]

    files = stored(app)
    assert len(files) == 1 and re.fullmatch(r"[a-f0-9]{32}\.webp", files[0])

    html = client.get("/").get_data(as_text=True)
    assert "home-slider" in html
    assert f"/slides/media/{files[0]}" in html
    assert 'href="/blog/"' in html
    assert "/static/js/slider.js" in html


def test_video_slide_mp4_and_webm(app, admin, client):
    create(admin, upload(MP4, "clip.mp4"), title="ویدیو یک")
    create(admin, upload(WEBM, "clip.webm"), title="ویدیو دو")

    assert [(r[0], r[1]) for r in rows(app)] == [("ویدیو یک", "video"), ("ویدیو دو", "video")]
    assert sorted(f.rsplit(".", 1)[1] for f in stored(app)) == ["mp4", "webm"]

    html = client.get("/").get_data(as_text=True)
    assert "<video" in html and "controls" in html

    name = next(f for f in stored(app) if f.endswith(".mp4"))
    response = client.get(f"/slides/media/{name}")

    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert "immutable" in response.headers["Cache-Control"]

    # پخش بخشی از ویدیو (Range) برای جلو/عقب‌کردن
    partial = client.get(f"/slides/media/{name}", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206 and len(partial.data) == 100


def test_fake_and_oversized_media_are_rejected_without_leftovers(app, admin):
    for data, name in [
        (b"not media at all", "x.png"),
        (b"<svg><script>alert(1)</script></svg>", "x.png"),
        (b"MZ\x90\x00" + b"\x00" * 100, "evil.mp4"),        # اجرایی با پسوند ویدیو
        (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100_000, "big.mp4"),  # بیش از سقف
        (b"", "empty.mp4"),
    ]:
        create(admin, upload(data, name))

    assert rows(app) == []
    assert stored(app) == []


def test_new_slide_requires_media(app, admin):
    response = admin.post("/slides/create", data={"title": "بدون فایل"},
                          content_type="multipart/form-data")

    assert response.status_code == 200
    assert rows(app) == []


def test_unsafe_link_is_rejected_and_never_rendered(app, admin, client):
    create(admin, upload(png()), link_url="javascript:alert(1)")
    assert rows(app) == []
    assert stored(app) == []

    # حتی اگر مقدار بد مستقیم به دیتابیس برسد، هنگام نمایش حذف می‌شود
    create(admin, upload(png()))
    with app.app_context():
        slide = HomeSlide.query.one()
        slide.link_url = "javascript:alert(1)"
        db.session.commit()

    assert "javascript:" not in client.get("/").get_data(as_text=True)


def test_text_is_escaped_on_home(app, admin, client):
    create(admin, upload(png()), title="<script>alert(1)</script>")

    html = client.get("/").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_slide_limit(app, admin):
    for number in range(8):
        create(admin, upload(png()), title=f"اسلاید {number}")

    response = create(admin, upload(png()), title="نهم")

    assert response.status_code == 302
    assert len(rows(app)) == 8


def test_toggle_hides_slide_from_home(app, admin, client):
    create(admin, upload(png()))

    admin.post("/slides/toggle/1")

    assert rows(app)[0][3] is False
    assert "home-slider" not in client.get("/").get_data(as_text=True)


def test_move_reorders_and_edges_are_safe(app, admin):
    for title in ("الف", "ب", "ج"):
        create(admin, upload(png()), title=title)

    admin.post("/slides/move/3/up")
    assert [r[0] for r in rows(app)] == ["الف", "ج", "ب"]

    admin.post("/slides/move/1/up")      # اولی بالاتر نمی‌رود
    admin.post("/slides/move/2/down")    # آخری پایین‌تر نمی‌رود
    assert [r[0] for r in rows(app)] == ["الف", "ج", "ب"]

    assert admin.post("/slides/move/1/sideways").status_code == 404
    assert admin.post("/slides/move/99/up").status_code == 404


def test_edit_keeps_or_replaces_file(app, admin):
    create(admin, upload(png()))
    first = stored(app)[0]

    admin.post("/slides/edit/1", data={"title": "عنوان جدید", "is_active": "y"},
               content_type="multipart/form-data")
    assert stored(app) == [first] and rows(app)[0][0] == "عنوان جدید"

    admin.post("/slides/edit/1",
               data={"title": "عنوان جدید", "is_active": "y",
                     "media": upload(MP4, "v.mp4")},
               content_type="multipart/form-data")

    files = stored(app)
    assert len(files) == 1 and files[0] != first and files[0].endswith(".mp4")
    assert rows(app)[0][1] == "video"

    # ویرایش با فایل خراب هیچ‌چیز را تغییر نمی‌دهد
    admin.post("/slides/edit/1",
               data={"title": "x" * 2, "is_active": "y", "media": upload(b"junk", "j.png")},
               content_type="multipart/form-data")
    assert stored(app) == files


def test_delete_removes_file_and_renumbers(app, admin):
    for title in ("الف", "ب", "ج"):
        create(admin, upload(png()), title=title)

    admin.post("/slides/delete/1")

    assert [(r[0], r[2]) for r in rows(app)] == [("ب", 0), ("ج", 1)]
    assert len(stored(app)) == 2


def test_media_route_rejects_bad_names(client):
    for name in ("../../etc/passwd", "x.webp", "A" * 32 + ".webp", "a" * 32 + ".exe",
                 "a" * 32 + ".webp.png", "a" * 32 + ".html"):
        assert client.get(f"/slides/media/{name}").status_code == 404

    assert client.get("/slides/media/" + "a" * 32 + ".webp").status_code == 404


def test_dashboard_links_to_slides(admin):
    assert "/slides/manage" in admin.get("/admin/").get_data(as_text=True)


def test_slide_admin_pages_are_not_cacheable(admin):
    assert "no-store" in admin.get("/slides/manage").headers["Cache-Control"]
