import re
from email.utils import format_datetime
from xml.sax.saxutils import escape as _xml_escape

from datetime import timezone

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect,
    render_template, request, send_from_directory, url_for
)
from flask_login import current_user, login_required
from markupsafe import Markup

from app.extensions import db
from app.modules.blog.forms import PostForm
from app.modules.blog.markup import render_body
from app.modules.blog.models import Post, PostImage
from sqlalchemy import or_
from app.modules.blog.slugs import RESERVED, slugify
from app.uploads import (
    is_stored_name, remove_image, save_image, upload_folder
)
from app.utils import to_latin_digits, utcnow_naive


blog_bp = Blueprint(
    "blog",
    __name__,
    url_prefix="/blog"
)

PUBLIC_PER_PAGE = 6
COVER_FOLDER = "blog"
ADMIN_PER_PAGE = 20
MAX_BODY_IMAGES = 12
FEED_LIMIT = 20


@blog_bp.app_template_filter("post_body")
def post_body_filter(text):
    return render_body(text)


def _page():
    try:
        return max(int(to_latin_digits(request.args.get("page", "1"))), 1)
    except ValueError:
        return 1


def _slug_taken(slug, post_id=None):
    query = Post.query.filter(Post.slug == slug)

    if post_id:
        query = query.filter(Post.id != post_id)

    return query.first() is not None


def _unique_slug(base, post_id=None):
    base = base or "post"
    candidate, number = base, 2

    while candidate in RESERVED or _slug_taken(candidate, post_id):
        suffix = f"-{number}"
        candidate = base[: 80 - len(suffix)] + suffix
        number += 1

    return candidate


def _resolve_slug(form, post):
    """(slug، خطا). اگر ادمین آدرس داده باشد باید دقیقاً همان آزاد باشد."""
    typed = slugify(form.slug.data) if form.slug.data else ""

    if typed:
        if typed in RESERVED:
            return None, "این آدرس رزرو شده است."

        if _slug_taken(typed, post.id if post else None):
            return None, "این آدرس قبلاً برای پست دیگری استفاده شده است."

        return typed, None

    if form.slug.data:
        return None, "آدرس باید شامل حروف یا عدد باشد."

    if post is not None:
        return post.slug, None  # در ویرایش، آدرس خالی یعنی بدون تغییر

    return _unique_slug(slugify(form.title.data)), None


# ------------------------------------------------------------ بخش عمومی

def _escape_like(text):
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


@blog_bp.route("/")
def index():
    search = request.args.get("q", "").strip()[:80]

    query = Post.query.filter(Post.is_published.is_(True))

    if search:
        pattern = f"%{_escape_like(search)}%"
        query = query.filter(
            or_(
                Post.title.ilike(pattern, escape="\\"),
                Post.excerpt.ilike(pattern, escape="\\"),
                Post.body.ilike(pattern, escape="\\"),
            )
        )

    pagination = query.order_by(
        Post.published_at.desc(), Post.id.desc()
    ).paginate(page=_page(), per_page=PUBLIC_PER_PAGE, error_out=False)

    return render_template(
        "blog/list.html",
        posts=pagination.items,
        pagination=pagination,
        search=search
    )


@blog_bp.route("/feed.xml")
def feed():
    """RSS 2.0 از آخرین پست‌های منتشرشده."""
    base = (current_app.config.get("SITE_URL") or request.url_root).rstrip("/")

    posts = Post.query.filter(
        Post.is_published.is_(True)
    ).order_by(
        Post.published_at.desc(), Post.id.desc()
    ).limit(FEED_LIMIT).all()

    def xml_escape(text):
        # نویسه‌های کنترلی در XML مجاز نیستند و کل فید را خراب می‌کنند
        return _xml_escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text)))

    def rfc822(moment):
        return format_datetime(moment.replace(tzinfo=timezone.utc))

    items = []

    for post in posts:
        link = f"{base}{url_for('blog.detail', slug=post.slug)}"
        stamp = post.published_at or post.created_at

        items.append(
            "<item>"
            f"<title>{xml_escape(post.title)}</title>"
            f"<link>{xml_escape(link)}</link>"
            f'<guid isPermaLink="true">{xml_escape(link)}</guid>'
            f"<pubDate>{rfc822(stamp)}</pubDate>"
            f"<description>{xml_escape(post.summary)}</description>"
            "</item>"
        )

    updated = rfc822(posts[0].published_at or posts[0].created_at) if posts else None
    home = f"{base}{url_for('blog.index')}"

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>وبلاگ CyberSite</title>"
        f"<link>{xml_escape(home)}</link>"
        "<description>آخرین نوشته‌های وبلاگ CyberSite</description>"
        "<language>fa</language>"
        + (f"<lastBuildDate>{updated}</lastBuildDate>" if updated else "")
        + "".join(items)
        + "</channel></rss>"
    )

    response = Response(xml, mimetype="application/rss+xml")
    response.headers["Cache-Control"] = "public, max-age=600"

    return response


@blog_bp.route("/<slug>")
def detail(slug):
    post = Post.query.filter_by(slug=slug).first()

    if post is None:
        abort(404)

    # پیش‌نویس فقط برای ادمین دیده می‌شود
    if not post.is_published and not current_user.is_authenticated:
        abort(404)

    # import محلی: ماژول نظرات خودش به مدل پست وابسته است
    from app.modules.comments.forms import CommentForm
    from app.modules.comments.routes import approved_comments

    return render_template(
        "blog/detail.html",
        post=post,
        comment_form=CommentForm(),
        comments=approved_comments(post),
        comments_enabled=current_app.config.get("COMMENTS_ENABLED", True),
    )


@blog_bp.route("/image/<filename>")
def cover_image(filename):
    # فقط نام‌هایی که خود برنامه ساخته است؛ هر چیز دیگر (از جمله ../) ۴۰۴ است
    if not is_stored_name(filename):
        abort(404)

    response = send_from_directory(
        upload_folder(COVER_FOLDER), filename, max_age=31536000
    )
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    return response


# ---------------------------------------------------------------- مدیریت

@blog_bp.route("/manage")
@login_required
def manage_posts():
    pagination = Post.query.order_by(
        Post.created_at.desc(), Post.id.desc()
    ).paginate(page=_page(), per_page=ADMIN_PER_PAGE, error_out=False)

    return render_template(
        "blog/manage.html",
        posts=pagination.items,
        pagination=pagination
    )


def _apply_body_images(form, post, saved, removed):
    """حذف عکس‌های علامت‌خورده و افزودن عکس‌های تازهٔ داخل متن."""
    wanted = {
        int(raw) for raw in request.form.getlist("delete_body_image")
        if raw.isdigit()
    }

    for image in list(post.body_images):
        if image.id in wanted:
            removed.append(image.filename)
            post.body_images.remove(image)

    files = [
        f for f in (form.images.data or [])
        if f and getattr(f, "filename", "")
    ]

    if len(post.body_images) + len(files) > MAX_BODY_IMAGES:
        raise ValueError(
            f"هر پست حداکثر {MAX_BODY_IMAGES} عکس داخل متن می‌تواند داشته باشد."
        )

    for file in files:
        name = save_image(file, COVER_FOLDER)
        saved.append(name)
        post.body_images.append(PostImage(filename=name))


def _save(form, post):
    slug, error = _resolve_slug(form, post)

    if error:
        form.slug.errors.append(error)
        return None

    try:
        new_cover = save_image(form.cover.data, COVER_FOLDER)
    except ValueError as error:
        form.cover.errors.append(str(error))
        return None

    creating = post is None
    saved_images = []
    removed_images = []

    if creating:
        post = Post()
        db.session.add(post)

    old_cover = post.cover_image
    drop_cover = bool(form.remove_cover.data) and not creating

    post.title = form.title.data
    post.slug = slug
    post.excerpt = form.excerpt.data or None
    post.body = form.body.data
    post.is_published = bool(form.is_published.data)

    if new_cover:
        post.cover_image = new_cover
    elif drop_cover:
        post.cover_image = None

    try:
        _apply_body_images(form, post, saved_images, removed_images)
    except ValueError as error:
        form.images.errors.append(str(error))
        remove_image(new_cover, COVER_FOLDER)

        for name in saved_images:
            remove_image(name, COVER_FOLDER)

        # تغییرات نیمه‌کارهٔ پست (عنوان، حذف عکس‌ها و ...) نباید در نشست بماند
        db.session.rollback()

        return None

    if post.is_published and post.published_at is None:
        post.published_at = utcnow_naive()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        remove_image(new_cover, COVER_FOLDER)

        for name in saved_images:
            remove_image(name, COVER_FOLDER)

        raise

    # فایل قدیمی فقط بعد از موفقیت ذخیره حذف می‌شود
    if old_cover and (new_cover or drop_cover):
        remove_image(old_cover, COVER_FOLDER)

    for name in removed_images:
        remove_image(name, COVER_FOLDER)

    return post


@blog_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_post():
    form = PostForm()

    if form.validate_on_submit():
        post = _save(form, None)

        if post is not None:
            flash("پست ذخیره شد.", "success")
            return redirect(url_for("blog.manage_posts"))

    return render_template(
        "blog/post_form.html", form=form, page_title="پست جدید", post=None
    )


@blog_bp.route("/edit/<int:post_id>", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    post = db.session.get(Post, post_id)

    if post is None:
        abort(404)

    form = PostForm(obj=post)

    if form.validate_on_submit():
        if _save(form, post) is not None:
            flash("پست به‌روزرسانی شد.", "success")
            return redirect(url_for("blog.manage_posts"))

        db.session.rollback()

    return render_template(
        "blog/post_form.html", form=form, page_title="ویرایش پست", post=post
    )


@blog_bp.route("/delete/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    post = db.session.get(Post, post_id)

    if post is None:
        abort(404)

    cover = post.cover_image
    inline = [image.filename for image in post.body_images]

    db.session.delete(post)
    db.session.commit()

    remove_image(cover, COVER_FOLDER)

    for name in inline:
        remove_image(name, COVER_FOLDER)

    flash("پست حذف شد.", "success")
    return redirect(url_for("blog.manage_posts"))
