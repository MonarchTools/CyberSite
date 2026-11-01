import hashlib
import hmac
from datetime import timedelta

from flask import (
    Blueprint, Response, abort, current_app, flash, make_response,
    redirect, render_template, request, url_for
)
from flask_login import login_required

from app.notifications import notify_new_message
from app.extensions import db
from app.modules.admin.captcha import create_challenge, verify_challenge
from app.modules.admin.throttle import client_ip
from app.modules.contact.forms import ContactForm
from app.modules.contact.models import ContactMessage
from app.utils import to_latin_digits, utcnow_naive


contact_bp = Blueprint(
    "contact",
    __name__,
    url_prefix="/contact"
)

CAPTCHA_PURPOSE = "contact"
PER_PAGE = 20


def _int(value, default):
    try:
        return int(to_latin_digits(str(value)).strip())
    except (TypeError, ValueError):
        return default


def _ip_hash():
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    message = f"contact-ip:{client_ip()}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _too_many_messages(ip_hash):
    limit = int(current_app.config.get("CONTACT_MAX_PER_HOUR", 5))
    since = utcnow_naive() - timedelta(hours=1)

    recent = ContactMessage.query.filter(
        ContactMessage.ip_hash == ip_hash,
        ContactMessage.created_at >= since,
    ).count()

    return recent >= limit


# ------------------------------------------------------------ بخش عمومی

@contact_bp.route("/", methods=["GET", "POST"])
def index():
    form = ContactForm()

    if form.validate_on_submit():
        if form.website.data:
            # ربات فیلد نامرئی را پر کرده است: موفق وانمود می‌کنیم و ذخیره نمی‌کنیم
            flash("پیام شما ارسال شد. سپاس!", "success")
            return redirect(url_for("contact.index"))

        ip_hash = _ip_hash()

        if _too_many_messages(ip_hash):
            flash(
                "تعداد پیام‌های ارسالی از این شبکه زیاد بوده است. "
                "بعداً دوباره تلاش کنید.",
                "danger"
            )
            response = make_response(
                render_template("contact/index.html", form=form), 429
            )
            response.headers["Retry-After"] = "3600"
            return response

        if not verify_challenge(form.captcha.data, purpose=CAPTCHA_PURPOSE):
            flash("کد امنیتی اشتباه یا منقضی شده است.", "danger")
            form.captcha.data = ""
            return render_template("contact/index.html", form=form)

        saved = ContactMessage(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data or None,
            subject=form.subject.data or None,
            message=form.message.data,
            ip_hash=ip_hash,
        )
        db.session.add(saved)
        db.session.commit()

        # بعد از ذخیره؛ خطای ایمیل هرگز پیام ذخیره‌شده را خراب نمی‌کند
        notify_new_message(saved)

        flash("پیام شما ارسال شد. سپاس!", "success")
        return redirect(url_for("contact.index"))

    return render_template("contact/index.html", form=form)


@contact_bp.route("/captcha.png")
def captcha():
    response = Response(
        create_challenge(CAPTCHA_PURPOSE), mimetype="image/png"
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ------------------------------------------------------- صندوق پیام (ادمین)

@contact_bp.route("/manage")
@login_required
def manage_messages():
    unread_only = request.args.get("filter") == "unread"
    page = max(_int(request.args.get("page"), 1), 1)

    query = ContactMessage.query

    if unread_only:
        query = query.filter(ContactMessage.is_read.is_(False))

    pagination = query.order_by(
        ContactMessage.created_at.desc(),
        ContactMessage.id.desc()
    ).paginate(page=page, per_page=PER_PAGE, error_out=False)

    return render_template(
        "contact/admin_list.html",
        pagination=pagination,
        messages=pagination.items,
        unread_only=unread_only,
        unread_count=unread_count()
    )


@contact_bp.route("/manage/<int:message_id>")
@login_required
def manage_message_detail(message_id):
    message = db.session.get(ContactMessage, message_id)

    if message is None:
        abort(404)

    if not message.is_read:
        message.is_read = True
        db.session.commit()

    return render_template("contact/admin_detail.html", message=message)


@contact_bp.route("/manage/<int:message_id>/delete", methods=["POST"])
@login_required
def delete_message(message_id):
    message = db.session.get(ContactMessage, message_id)

    if message is None:
        abort(404)

    db.session.delete(message)
    db.session.commit()

    flash("پیام حذف شد.", "success")
    return redirect(url_for("contact.manage_messages"))


def unread_count():
    return ContactMessage.query.filter(
        ContactMessage.is_read.is_(False)
    ).count()
