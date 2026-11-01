
from flask import (
    Blueprint, Response, flash, make_response, redirect,
    render_template, session, url_for
)
from flask_login import (
    current_user, login_required, login_user, logout_user
)
from werkzeug.security import check_password_hash, generate_password_hash

from app.modules.admin.captcha import create_challenge, verify_challenge
from app.modules.admin.forms import LoginForm
from app.modules.admin.models import Admin
from app.modules.contact.models import ContactMessage
from app.modules.admin.throttle import (
    lock_remaining,
    register_failure,
    register_success,
)


admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin"
)

# برای کاربر ناموجود هم یک هش واقعی بررسی می‌شود تا زمان پاسخ،
# وجود یا نبود نام کاربری را لو ندهد.
_DUMMY_HASH = generate_password_hash("timing-equalizer-not-a-real-password")


@admin_bp.route("/", methods=["GET"])
@login_required
def index():
    unread_messages = ContactMessage.query.filter(
        ContactMessage.is_read.is_(False)
    ).count()

    return render_template(
        "admin/dashboard.html",
        admin=current_user,
        unread_messages=unread_messages
    )


def _locked_response(form, seconds):
    minutes = max((seconds + 59) // 60, 1)

    flash(
        f"تلاش‌های ناموفق زیاد بود. حدود {minutes} دقیقهٔ دیگر دوباره امتحان کنید.",
        "danger"
    )

    response = make_response(
        render_template("admin/login.html", form=form, locked=True),
        429
    )
    response.headers["Retry-After"] = str(seconds)

    return response


def _failed_response(form, message):
    """شکست را ثبت می‌کند؛ اگر همین تلاش قفل را فعال کرد، پاسخ قفل می‌دهد."""
    register_failure()

    seconds = lock_remaining()

    if seconds:
        return _locked_response(form, seconds)

    flash(message, "danger")
    form.captcha.data = ""

    return render_template("admin/login.html", form=form)


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.index"))

    form = LoginForm()

    seconds = lock_remaining()

    if seconds:
        # در زمان قفل، اطلاعات ارسال‌شده اصلاً بررسی نمی‌شود
        return _locked_response(form, seconds)

    if form.validate_on_submit():
        # کپچا پیش از هر بررسی نام کاربری و رمز انجام می‌شود
        if not verify_challenge(form.captcha.data):
            return _failed_response(
                form, "کد امنیتی اشتباه یا منقضی شده است."
            )

        admin = Admin.query.filter_by(
            username=form.username.data.strip()
        ).first()

        if admin is not None:
            valid = admin.check_password(form.password.data)
        else:
            check_password_hash(_DUMMY_HASH, form.password.data)
            valid = False

        if valid:
            register_success()

            # شناسهٔ نشست قدیمی دور ریخته می‌شود (جلوگیری از session fixation)
            session.clear()
            login_user(admin, remember=False)
            session.permanent = True

            flash("ورود موفقیت‌آمیز بود.", "success")
            return redirect(url_for("admin.index"))

        return _failed_response(
            form, "نام کاربری یا رمز عبور اشتباه است."
        )

    return render_template("admin/login.html", form=form)


@admin_bp.route("/captcha.png", methods=["GET"])
def captcha():
    seconds = lock_remaining()

    if seconds:
        # IP قفل‌شده تصویر جدید نمی‌گیرد (جلوگیری از فشار بی‌دلیل روی دیتابیس)
        response = Response("Too many attempts", status=429)
        response.headers["Retry-After"] = str(seconds)
        return response

    response = Response(create_challenge(), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@admin_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("با موفقیت خارج شدید.", "success")
    return redirect(url_for("admin.login"))
