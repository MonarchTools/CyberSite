import hashlib
import hmac
import re
from datetime import timedelta

from flask import (
    Blueprint, Response, abort, current_app, flash, make_response,
    redirect, render_template, request, url_for
)
from flask_login import login_required

from app.extensions import db
from app.modules.admin.captcha import create_challenge, verify_challenge
from app.modules.admin.throttle import client_ip
from app.modules.blog.models import Post
from app.modules.comments.forms import CommentForm
from app.modules.comments.models import Comment, CommentStatus
from app.notifications import notify_new_comment
from app.utils import to_latin_digits, utcnow_naive


comments_bp = Blueprint("comments", __name__, url_prefix="/blog")

CAPTCHA_PURPOSE = "comment"
PER_PAGE = 20

# لینک و نشانی سایت در نظر مجاز نیست (راه اصلی اسپم)
_LINKISH = re.compile(
    r"(https?:|www\.|\bt\.me/|\.(?:com|net|org|ir|info|xyz|ru|top|site|shop)\b)",
    re.IGNORECASE
)


def _ip_hash():
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    message = f"comment-ip:{client_ip()}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def approved_comments(post):
    return Comment.query.filter(
        Comment.post_id == post.id,
        Comment.status == CommentStatus.APPROVED
    ).order_by(Comment.created_at, Comment.id).all()


def pending_count():
    return Comment.query.filter(
        Comment.status == CommentStatus.PENDING
    ).count()


def render_post(post, form, status=200):
    response = make_response(render_template(
        "blog/detail.html",
        post=post,
        comment_form=form,
        comments=approved_comments(post),
        comments_enabled=current_app.config.get("COMMENTS_ENABLED", True),
    ), status)
    return response


def _too_many(ip_hash):
    limit = int(current_app.config.get("COMMENT_MAX_PER_HOUR", 5))
    since = utcnow_naive() - timedelta(hours=1)

    return Comment.query.filter(
        Comment.ip_hash == ip_hash,
        Comment.created_at >= since
    ).count() >= limit


# ------------------------------------------------------------ بخش عمومی

@comments_bp.route("/comment-captcha.png")
def captcha():
    response = Response(create_challenge(CAPTCHA_PURPOSE), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@comments_bp.route("/<slug>/comment", methods=["POST"])
def submit(slug):
    post = Post.query.filter_by(slug=slug, is_published=True).first()

    if post is None or not current_app.config.get("COMMENTS_ENABLED", True):
        abort(404)

    form = CommentForm()
    back = url_for("blog.detail", slug=post.slug) + "#comments"

    if not form.validate_on_submit():
        return render_post(post, form, 400)

    if form.website.data:
        # ربات فیلد نامرئی را پر کرده است: موفق وانمود می‌کنیم و ذخیره نمی‌کنیم
        flash("نظر شما ثبت شد و پس از تأیید نمایش داده می‌شود.", "success")
        return redirect(back)

    ip_hash = _ip_hash()

    if _too_many(ip_hash):
        flash("تعداد نظرهای ارسالی از این شبکه زیاد بوده است. بعداً دوباره تلاش کنید.", "danger")
        response = render_post(post, form, 429)
        response.headers["Retry-After"] = "3600"
        return response

    if not verify_challenge(form.captcha.data, purpose=CAPTCHA_PURPOSE):
        flash("کد امنیتی اشتباه یا منقضی شده است.", "danger")
        form.captcha.data = ""
        return render_post(post, form, 400)

    if _LINKISH.search(form.body.data) or _LINKISH.search(form.name.data):
        form.body.errors.append("ارسال لینک یا آدرس سایت در نظر مجاز نیست.")
        return render_post(post, form, 400)

    duplicate = Comment.query.filter(
        Comment.post_id == post.id,
        Comment.name == form.name.data,
        Comment.body == form.body.data
    ).first()

    if duplicate is not None:
        flash("این نظر قبلاً ثبت شده است.", "warning")
        return redirect(back)

    auto = current_app.config.get("COMMENTS_AUTO_APPROVE", False)

    comment = Comment(
        post_id=post.id,
        name=form.name.data,
        body=form.body.data,
        status=CommentStatus.APPROVED if auto else CommentStatus.PENDING,
        ip_hash=ip_hash,
    )
    db.session.add(comment)
    db.session.commit()

    # بعد از ذخیره؛ خطای ایمیل هرگز نظر ذخیره‌شده را خراب نمی‌کند
    notify_new_comment(comment, post)

    flash(
        "نظر شما ثبت شد." if auto
        else "نظر شما ثبت شد و پس از تأیید مدیر نمایش داده می‌شود.",
        "success"
    )
    return redirect(back)


# ------------------------------------------------------------------ مدیریت

FILTERS = ("pending", "approved", "all")


def _page():
    try:
        return max(int(to_latin_digits(request.args.get("page", "1"))), 1)
    except ValueError:
        return 1


@comments_bp.route("/comments")
@login_required
def manage_comments():
    current = request.args.get("filter", "pending")

    if current not in FILTERS:
        current = "pending"

    query = Comment.query.join(Post)

    if current != "all":
        query = query.filter(Comment.status == current)

    pagination = query.order_by(
        Comment.created_at.desc(), Comment.id.desc()
    ).paginate(page=_page(), per_page=PER_PAGE, error_out=False)

    return render_template(
        "comments/manage.html",
        pagination=pagination,
        comments=pagination.items,
        current=current,
        pending=pending_count(),
        statuses=CommentStatus
    )


def _redirect_back():
    current = request.form.get("filter", "pending")
    return redirect(url_for(
        "comments.manage_comments",
        filter=current if current in FILTERS else "pending"
    ))


def _get_or_404(comment_id):
    comment = db.session.get(Comment, comment_id)

    if comment is None:
        abort(404)

    return comment


@comments_bp.route("/comments/<int:comment_id>/approve", methods=["POST"])
@login_required
def approve_comment(comment_id):
    _get_or_404(comment_id).status = CommentStatus.APPROVED
    db.session.commit()
    flash("نظر تأیید شد.", "success")
    return _redirect_back()


@comments_bp.route("/comments/<int:comment_id>/hide", methods=["POST"])
@login_required
def hide_comment(comment_id):
    _get_or_404(comment_id).status = CommentStatus.PENDING
    db.session.commit()
    flash("نظر از نمایش عمومی برداشته شد.", "success")
    return _redirect_back()


@comments_bp.route("/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    db.session.delete(_get_or_404(comment_id))
    db.session.commit()
    flash("نظر حذف شد.", "success")
    return _redirect_back()
