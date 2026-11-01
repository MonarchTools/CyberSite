
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user



from flask import (
    Blueprint, render_template, redirect,
    url_for, flash
)
from flask_login import (
    login_user, logout_user,
    login_required, current_user
)

from app.modules.admin.models import Admin
from app.modules.admin.forms import LoginForm
from app.modules.admin.captcha import create_challenge, verify_challenge
from flask import Response


admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin"
)


@admin_bp.route("/", methods=["GET"])
@login_required
def index():
    return render_template(
        "admin/dashboard.html",
        admin=current_user
    )


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.index"))

    form = LoginForm()

    if form.validate_on_submit():
        # کپچا پیش از هر بررسی نام کاربری و رمز انجام می‌شود
        if not verify_challenge(form.captcha.data):
            flash("کد امنیتی اشتباه یا منقضی شده است.", "danger")
            form.captcha.data = ""
            return render_template("admin/login.html", form=form)

        admin = Admin.query.filter_by(
            username=form.username.data.strip()
        ).first()

        if admin and admin.check_password(form.password.data):
            login_user(admin, remember=False)
            flash("ورود موفقیت‌آمیز بود.", "success")
            return redirect(url_for("admin.index"))

        flash("نام کاربری یا رمز عبور اشتباه است.", "danger")

    return render_template("admin/login.html", form=form)


@admin_bp.route("/captcha.png", methods=["GET"])
def captcha():
    response = Response(create_challenge(), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@admin_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("با موفقیت خارج شدید.", "success")
    return redirect(url_for("admin.login"))
