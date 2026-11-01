import io
import re
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.blog.markup import render_body
from app.modules.blog.models import Post
from app.modules.blog.slugs import slugify
from config import Config


PASSWORD = "a-very-long-password-123"
BODY = "این یک متن آزمایشی برای پست وبلاگ است."


# ------------------------------------------------------- رندر امن (خالص)

@pytest.mark.parametrize(
    "bad_link",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "vbscript:x",
        "data:text/html,x",
        "//evil.example",
    ],
)
def test_unsafe_links_are_not_rendered(bad_link):
    assert "<a " not in str(render_body(f"[x]({bad_link})"))


def test_raw_html_is_escaped():
    html = str(render_body("<script>alert(1)</script> <img src=x onerror=y>"))

    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_attribute_breakout_is_impossible():
    html = str(render_body('[x](https://a.example/"onmouseover="alert(1))'))

    assert 'onmouseover="' not in html


def test_formatting():
    assert str(render_body("## سلام")) == "<h2>سلام</h2>"
    assert str(render_body("## سلام\nمتن")) == "<h2>سلام</h2>\n<p>متن</p>"
    assert str(render_body("**a** و *b*")) == "<p><strong>a</strong> و <em>b</em></p>"
    assert str(render_body("- a\n- b")) == "<ul><li>a</li><li>b</li></ul>"
    assert "<pre><code>" in str(render_body("```\nx = 1\n```"))


def test_code_block_is_literal():
    html = str(render_body("```\n<b>**x**</b>\n```"))

    assert "&lt;b&gt;**x**&lt;/b&gt;" in html
    assert "<strong>" not in html


def test_slugify():
    assert slugify("سلام دنیا") == "سلام-دنیا"
    assert slugify("  Hello   World!! ") == "hello-world"
    assert slugify("../../etc/passwd") == "etcpasswd"
    assert slugify("---") == ""
    assert slugify("a" * 300) == "a" * 80


# ------------------------------------------------------------ وب‌سایت

class BlogTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")

    app = create_app(BlogTestConfig)
    app.instance_path = str(tmp_path)   # آپلودهای تست داخل پوشهٔ موقت می‌مانند

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
def admin(client):
    client.get("/admin/captcha.png")
    client.post(
        "/admin/login",
        data={"username": "owner", "password": PASSWORD, "captcha": "ABCDE"},
    )
    return client


def create(client, title="پست اول", slug="", published=True, body=BODY, **extra):
    data = {"title": title, "slug": slug, "excerpt": "", "body": body, **extra}

    if published:
        data["is_published"] = "y"

    return client.post("/blog/create", data=data)


def posts(app):
    with app.app_context():
        return Post.query.order_by(Post.id).all()


# -------------------------------------------------------------- عمومی

def test_blog_list_is_public_and_empty_state(client):
    response = client.get("/blog/")

    assert response.status_code == 200
    assert "هنوز نوشته‌ای منتشر نشده است" in response.get_data(as_text=True)


def test_published_post_visible_draft_hidden(app, admin):
    create(admin, title="منتشرشده", slug="pub", published=True)
    create(admin, title="پیش‌نویس‌من", slug="draft", published=False)

    public = app.test_client()

    listing = public.get("/blog/").get_data(as_text=True)
    assert "منتشرشده" in listing
    assert "پیش‌نویس‌من" not in listing

    assert public.get("/blog/pub").status_code == 200
    assert public.get("/blog/draft").status_code == 404


def test_admin_can_preview_draft(admin):
    create(admin, title="پیش‌نویس", slug="draft", published=False)

    response = admin.get("/blog/draft")

    assert response.status_code == 200
    assert "پیش‌نویس است" in response.get_data(as_text=True)


def test_unknown_post_is_404(client):
    assert client.get("/blog/nope").status_code == 404


def test_post_body_is_rendered_safely(admin):
    create(
        admin,
        slug="x",
        body="## بخش\n<script>alert(1)</script> **مهم** [لینک](javascript:alert(1))",
    )

    html = admin.get("/blog/x").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "<h2>بخش</h2>" in html
    assert "<strong>مهم</strong>" in html
    assert 'href="javascript:' not in html


def test_title_is_escaped(admin):
    create(admin, title="<img src=x onerror=alert(1)>", slug="t")

    html = admin.get("/blog/").get_data(as_text=True)

    assert "<img src=x" not in html


def test_public_pagination(admin):
    for number in range(8):
        create(admin, title=f"پست {number}", slug=f"p{number}")

    public = admin.application.test_client()

    assert public.get("/blog/").get_data(as_text=True).count("post-card") == 6
    assert public.get("/blog/?page=2").get_data(as_text=True).count("post-card") == 2
    assert public.get("/blog/?page=999").status_code == 200
    assert public.get("/blog/?page=abc").status_code == 200


# ------------------------------------------------------------- مدیریت

@pytest.mark.parametrize(
    "url", ["/blog/manage", "/blog/create", "/blog/edit/1"]
)
def test_management_requires_login(client, url):
    response = client.get(url)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_delete_requires_login_and_post(app, admin):
    create(admin, slug="a")

    assert admin.application.test_client().post("/blog/delete/1").status_code == 302
    assert len(posts(app)) == 1

    assert admin.get("/blog/delete/1").status_code == 405
    assert len(posts(app)) == 1


def test_create_edit_delete_flow(app, admin):
    assert create(admin, title="عنوان", slug="first").status_code == 302

    saved = posts(app)[0]
    assert saved.slug == "first"
    assert saved.published_at is not None

    response = admin.post(
        f"/blog/edit/{saved.id}",
        data={"title": "عنوان جدید", "slug": "", "excerpt": "", "body": BODY},
    )

    assert response.status_code == 302

    edited = posts(app)[0]
    assert edited.title == "عنوان جدید"
    assert edited.slug == "first"          # آدرس خالی یعنی بدون تغییر
    assert edited.is_published is False    # تیک انتشار برداشته شده

    assert admin.post(f"/blog/delete/{saved.id}").status_code == 302
    assert posts(app) == []


def test_slug_is_generated_from_title_and_made_unique(app, admin):
    create(admin, title="سلام دنیا")
    create(admin, title="سلام دنیا")

    assert [p.slug for p in posts(app)] == ["سلام-دنیا", "سلام-دنیا-2"]


def test_explicit_duplicate_slug_is_rejected(app, admin):
    create(admin, slug="same")

    response = create(admin, title="دیگری", slug="same")

    assert response.status_code == 200
    assert "قبلاً" in response.get_data(as_text=True)
    assert len(posts(app)) == 1


@pytest.mark.parametrize("reserved", ["manage", "create", "edit"])
def test_reserved_slug_is_rejected(app, admin, reserved):
    response = create(admin, slug=reserved)

    assert response.status_code == 200
    assert posts(app) == []


def test_title_that_slugifies_to_reserved_word_gets_suffix(app, admin):
    create(admin, title="manage")

    assert posts(app)[0].slug == "manage-2"


def test_manage_route_is_not_shadowed_by_slug(admin):
    assert admin.get("/blog/manage").status_code == 200


def test_validation_errors_keep_form(app, admin):
    response = create(admin, title="ab", body="کوتاه")

    assert response.status_code == 200
    assert posts(app) == []


def test_edit_cannot_steal_other_slug(app, admin):
    create(admin, slug="one")
    create(admin, title="دو", slug="two")

    second = posts(app)[1]
    response = admin.post(
        f"/blog/edit/{second.id}",
        data={"title": "دو", "slug": "one", "excerpt": "", "body": BODY},
    )

    assert response.status_code == 200
    assert posts(app)[1].slug == "two"


def test_manage_pages_are_not_cacheable(admin):
    assert "no-store" in admin.get("/blog/manage").headers["Cache-Control"]
    assert "no-store" in admin.get("/blog/create").headers["Cache-Control"]


def test_summary_strips_markup(app, admin):
    create(admin, slug="s", body="## تیتر\n**مهم** و [لینک](https://a.example) ساده")

    summary = posts(app)[0].summary

    assert "#" not in summary and "*" not in summary and "](" not in summary
    assert "لینک" in summary


# ------------------------------------------------------------ تصویر شاخص

def png_bytes(size=(40, 30), color=(200, 30, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def upload(data, name="cover.png"):
    return (io.BytesIO(data), name)


def cover_dir(app):
    return Path(app.instance_path) / "uploads" / "blog"


def stored_files(app):
    folder = cover_dir(app)
    return sorted(p.name for p in folder.glob("*")) if folder.exists() else []


def test_cover_is_saved_as_clean_webp_and_served(app, admin):
    response = create(admin, slug="c", cover=upload(png_bytes()))

    assert response.status_code == 302

    name = posts(app)[0].cover_image

    assert re.fullmatch(r"[a-f0-9]{32}\.webp", name)
    assert stored_files(app) == [name]

    with Image.open(cover_dir(app) / name) as saved:
        assert saved.format == "WEBP"

    public = app.test_client()
    served = public.get(f"/blog/image/{name}")

    assert served.status_code == 200
    assert served.mimetype == "image/webp"
    assert "immutable" in served.headers["Cache-Control"]
    assert served.headers["X-Content-Type-Options"] == "nosniff"


def test_exif_metadata_is_stripped(app, admin):
    exif = Image.Exif()
    exif[0x010E] = "secret description"
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (1, 2, 3)).save(buffer, "JPEG", exif=exif)

    create(admin, slug="e", cover=upload(buffer.getvalue(), "photo.jpg"))

    name = posts(app)[0].cover_image

    with Image.open(cover_dir(app) / name) as saved:
        assert not dict(saved.getexif())

    assert b"secret description" not in (cover_dir(app) / name).read_bytes()


def test_large_image_is_downscaled(app, admin):
    create(admin, slug="big", cover=upload(png_bytes((3200, 1800))))

    name = posts(app)[0].cover_image

    with Image.open(cover_dir(app) / name) as saved:
        assert max(saved.size) <= 1600


@pytest.mark.parametrize(
    "data,name",
    [
        (b"this is not an image", "x.png"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.png"),
        (b"GIF89a" + b"\x00" * 40, "x.png"),
    ],
)
def test_fake_images_are_rejected(app, admin, data, name):
    response = create(admin, slug="bad", cover=upload(data, name))

    assert response.status_code == 200
    assert posts(app) == []
    assert stored_files(app) == []


def test_wrong_extension_is_rejected(app, admin):
    response = create(admin, slug="gif", cover=upload(png_bytes(), "x.gif"))

    assert response.status_code == 200
    assert posts(app) == []


def test_replace_and_remove_cover_delete_old_files(app, admin):
    create(admin, slug="r", cover=upload(png_bytes()))
    first = posts(app)[0].cover_image

    base = {"title": "عنوان", "slug": "", "excerpt": "", "body": BODY, "is_published": "y"}

    admin.post("/blog/edit/1", data={**base, "cover": upload(png_bytes(color=(0, 255, 0)))})
    second = posts(app)[0].cover_image

    assert second != first
    assert stored_files(app) == [second]

    admin.post("/blog/edit/1", data={**base, "remove_cover": "y"})

    assert posts(app)[0].cover_image is None
    assert stored_files(app) == []


def test_edit_without_new_file_keeps_cover(app, admin):
    create(admin, slug="k", cover=upload(png_bytes()))
    name = posts(app)[0].cover_image

    admin.post("/blog/edit/1", data={"title": "عنوان", "slug": "", "excerpt": "", "body": BODY})

    assert posts(app)[0].cover_image == name
    assert stored_files(app) == [name]


def test_deleting_post_removes_cover_file(app, admin):
    create(admin, slug="d", cover=upload(png_bytes()))

    admin.post("/blog/delete/1")

    assert posts(app) == []
    assert stored_files(app) == []


@pytest.mark.parametrize(
    "path",
    [
        "/blog/image/../../config.py",
        "/blog/image/..%2f..%2fconfig.py",
        "/blog/image/notahash.webp",
        "/blog/image/" + "a" * 32 + ".png",
        "/blog/image/" + "a" * 32 + ".webp",   # نام درست ولی فایل وجود ندارد
    ],
)
def test_image_route_rejects_bad_names(client, path):
    assert client.get(path).status_code == 404


def test_cover_shown_on_list_and_detail(app, admin):
    create(admin, slug="v", cover=upload(png_bytes()))
    name = posts(app)[0].cover_image
    public = app.test_client()

    assert f"/blog/image/{name}" in public.get("/blog/").get_data(as_text=True)
    assert f"/blog/image/{name}" in public.get("/blog/v").get_data(as_text=True)


def test_post_without_cover_uses_placeholder(admin):
    create(admin, slug="n")

    assert "post-cover-placeholder" in admin.application.test_client().get("/blog/").get_data(as_text=True)


# ----------------------------------------------- ارتقای دیتابیس، خطاها، ظاهر

def test_upgrade_adds_missing_column_once(app):
    from app.db_upgrade import upgrade_schema

    with app.app_context():
        db.session.remove()
        db.session.execute(text("DROP TABLE posts"))
        db.session.execute(text(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, title VARCHAR(150) NOT NULL, "
            "slug VARCHAR(80) NOT NULL, excerpt VARCHAR(300), body TEXT NOT NULL, "
            "is_published BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, published_at DATETIME)"
        ))
        db.session.commit()

        assert upgrade_schema() == ["posts.cover_image"]
        assert upgrade_schema() == []


def test_friendly_error_pages(client):
    missing = client.get("/no-such-page")

    assert missing.status_code == 404
    html = missing.get_data(as_text=True)
    assert "صفحه پیدا نشد" in html
    assert "ERROR 404" in html

    assert client.post("/").status_code == 405


def test_theme_toggle_and_font_assets(client):
    html = client.get("/").get_data(as_text=True)

    assert "data-theme-toggle" in html
    assert "js/theme-init.js" in html
    assert 'rel="icon"' in html

    assert client.get("/static/fonts/Vazirmatn-Variable.woff2").status_code == 200
    assert client.get("/static/favicon.svg").status_code == 200
