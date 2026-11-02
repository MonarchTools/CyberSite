import pytest

from app import create_app, notifications
from app.extensions import db
from app.modules.admin import captcha as captcha_module
from app.modules.admin.models import Admin
from app.modules.blog.models import Post
from app.modules.comments.models import Comment
from app.utils import utcnow_naive
from config import Config


PASSWORD = "a-very-long-password-123"

VALID = {
    "name": "مریم",
    "body": "نوشتهٔ خیلی خوبی بود، ممنون از وقتی که گذاشتید.",
    "website": "",
    "captcha": "ABCDE",
}


class CommentConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    COMMENT_MAX_PER_HOUR = 3
    MAIL_SERVER = "smtp.example.test"
    MAIL_FROM = "shop@example.test"
    ADMIN_NOTIFY_EMAIL = "owner@example.test"
    MAIL_ASYNC = False
    SITE_URL = "https://site.example.test"


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "_send_smtp", lambda s, m: sent.append(m))
    return sent


@pytest.fixture()
def app(monkeypatch, outbox):
    monkeypatch.setattr(captcha_module, "_random_text", lambda: "ABCDE")
    app = create_app(CommentConfig)

    with app.app_context():
        admin = Admin(username="owner")
        admin.set_password(PASSWORD)
        db.session.add(admin)
        db.session.add_all([
            Post(title="پست منتشرشده", slug="hello", body="متن کافی برای پست.",
                 is_published=True, published_at=utcnow_naive()),
            Post(title="پیش‌نویس", slug="draft", body="متن کافی برای پیش‌نویس.",
                 is_published=False),
        ])
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


def comment(client, slug="hello", fetch_captcha=True, **overrides):
    if fetch_captcha:
        client.get("/blog/comment-captcha.png")

    return client.post(f"/blog/{slug}/comment", data={**VALID, **overrides})


def count(app, **filters):
    with app.app_context():
        return Comment.query.filter_by(**filters).count()


# ------------------------------------------------------------- بخش عمومی

def test_post_page_has_comment_form(client):
    html = client.get("/blog/hello").get_data(as_text=True)

    assert 'action="/blog/hello/comment"' in html
    assert "/blog/comment-captcha.png" in html
    assert "هنوز نظری ثبت نشده است" in html


def test_captcha_image(client):
    response = client.get("/blog/comment-captcha.png")

    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]


def test_new_comment_is_pending_and_hidden_until_approved(app, client, admin):
    response = comment(client)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/blog/hello#comments")
    assert count(app, status="pending") == 1
    assert "نوشتهٔ خیلی خوبی بود" not in client.get("/blog/hello").get_data(as_text=True)

    admin.post("/blog/comments/1/approve", data={"filter": "pending"})

    html = client.get("/blog/hello").get_data(as_text=True)
    assert "نوشتهٔ خیلی خوبی بود" in html and "مریم" in html
    assert "نظرات (1)" in html


def test_ip_is_stored_only_as_hash(app, client):
    comment(client)

    with app.app_context():
        saved = Comment.query.one()
        assert "127.0.0.1" not in saved.ip_hash and len(saved.ip_hash) == 64


def test_comment_text_is_escaped(app, client, admin):
    comment(client, name="<b>x</b>مریم", body="<script>alert(1)</script> متن کافی است")
    admin.post("/blog/comments/1/approve")

    html = client.get("/blog/hello").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>x</b>" not in html


def test_wrong_captcha_is_rejected_and_text_is_kept(app, client):
    response = comment(client, captcha="ZZZZZ")
    html = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "کد امنیتی" in html
    assert "نوشتهٔ خیلی خوبی بود" in html          # متن کاربر از دست نمی‌رود
    assert count(app) == 0


def test_captcha_is_single_use_and_purpose_bound(app, client):
    assert comment(client).status_code == 302
    assert comment(client, fetch_captcha=False, body="نظر دوم با همان کد قبلی").status_code == 400

    other = app.test_client()
    other.get("/contact/captcha.png")             # چالش فرم تماس، نه نظر
    assert comment(other, fetch_captcha=False).status_code == 400


def test_honeypot_silently_drops_bots(app, client):
    response = comment(client, website="http://spam.example")

    assert response.status_code == 302
    assert count(app) == 0


@pytest.mark.parametrize("overrides", [
    {"name": ""},
    {"name": "ا"},
    {"body": "کوتاه"},
    {"body": "ا" * 1001},
])
def test_invalid_input_is_rejected(app, client, overrides):
    assert comment(client, **overrides).status_code == 400
    assert count(app) == 0


@pytest.mark.parametrize("body", [
    "بیایید به http://spam.example سر بزنید",
    "سایت من www.spam.example است",
    "بخرید از shop.spam.com همین حالا",
    "کانال من t.me/spamchannel است",
])
def test_links_are_rejected(app, client, body):
    response = comment(client, body=body)

    assert response.status_code == 400
    assert "لینک" in response.get_data(as_text=True)
    assert count(app) == 0


def test_duplicate_comment_is_not_saved_twice(app, client):
    comment(client)
    comment(client)

    assert count(app) == 1


def test_rate_limit_per_ip(app, client):
    for index in range(3):
        assert comment(client, body=f"نظر شمارهٔ {index} برای آزمایش").status_code == 302

    response = comment(client, body="نظر چهارم که باید رد شود")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert count(app) == 3


def test_draft_and_unknown_posts_are_404(app, client):
    assert comment(client, slug="draft").status_code == 404
    assert comment(client, slug="nope").status_code == 404
    assert count(app) == 0


def test_comments_can_be_disabled(app, client):
    app.config["COMMENTS_ENABLED"] = False

    assert comment(client).status_code == 404
    assert "ثبت نظر جدید فعلاً بسته است" in client.get("/blog/hello").get_data(as_text=True)


def test_auto_approve_setting(app, client):
    app.config["COMMENTS_AUTO_APPROVE"] = True
    comment(client)

    assert count(app, status="approved") == 1
    assert "نوشتهٔ خیلی خوبی بود" in client.get("/blog/hello").get_data(as_text=True)


def test_deleting_post_removes_its_comments(app, client, admin):
    comment(client)
    admin.post("/blog/delete/1")

    assert count(app) == 0


# --------------------------------------------------------------- مدیریت

@pytest.mark.parametrize("method,url", [
    ("get", "/blog/comments"),
    ("post", "/blog/comments/1/approve"),
    ("post", "/blog/comments/1/hide"),
    ("post", "/blog/comments/1/delete"),
])
def test_moderation_requires_login(app, client, method, url):
    comment(client)
    response = getattr(client, method)(url)

    assert response.status_code == 302 and "/admin/login" in response.headers["Location"]
    assert count(app, status="pending") == 1


def test_actions_need_post(app, client, admin):
    comment(client)

    assert admin.get("/blog/comments/1/delete").status_code == 405
    assert count(app) == 1


def test_moderation_flow(app, client, admin):
    comment(client)

    listing = admin.get("/blog/comments").get_data(as_text=True)
    assert "مریم" in listing and "در انتظار تأیید" in listing

    admin.post("/blog/comments/1/approve", data={"filter": "pending"})
    assert count(app, status="approved") == 1
    assert "مریم" not in admin.get("/blog/comments").get_data(as_text=True)   # فیلتر پیش‌فرض: در انتظار
    assert "مریم" in admin.get("/blog/comments?filter=approved").get_data(as_text=True)

    admin.post("/blog/comments/1/hide")
    assert count(app, status="pending") == 1

    assert admin.post("/blog/comments/1/delete").status_code == 302
    assert count(app) == 0
    assert admin.post("/blog/comments/99/approve").status_code == 404


def test_bad_filter_value_falls_back(admin):
    assert admin.get("/blog/comments?filter=../../x").status_code == 200
    assert admin.post("/blog/comments/99/delete", data={"filter": "evil"}).status_code == 404


def test_dashboard_badge_and_not_cacheable(app, client, admin):
    comment(client)

    assert 'class="card-badge">1<' in admin.get("/admin/").get_data(as_text=True)
    assert "no-store" in admin.get("/blog/comments").headers["Cache-Control"]

    admin.post("/blog/comments/1/approve")
    assert "card-badge" not in admin.get("/admin/").get_data(as_text=True)


def test_new_comment_emails_admin(app, client, outbox):
    comment(client)

    assert len(outbox) == 1
    assert outbox[0]["To"] == "owner@example.test"
    assert "پست منتشرشده" in outbox[0]["Subject"]
    assert "https://site.example.test/blog/comments" in outbox[0].get_content()

    comment(client, captcha="ZZZZZ")        # ردشده: ایمیل نمی‌رود
    assert len(outbox) == 1
