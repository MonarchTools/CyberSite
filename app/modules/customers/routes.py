import mimetypes

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect,
    render_template, request, send_from_directory, url_for
)
from sqlalchemy import update
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.modules.admin.captcha import create_challenge, verify_challenge
from app.modules.admin.throttle import (
    lock_remaining, register_failure, register_success
)
from app.modules.customers.auth import (
    current_customer, customer_required, login_customer, logout_customer,
    safe_next
)
from app.modules.customers.forms import (
    ChangePasswordForm, ForgotPasswordForm, LoginForm, RegisterForm,
    ResetPasswordForm
)
from app.modules.customers.models import Customer
from app.modules.customers.reset import make_token, read_token, reset_minutes
from app.notifications import is_configured, send_mail
from app.seo import base_url
from app.modules.products.files import stored_path
from app.modules.products.models import Product
from app.modules.shop.models import Order, OrderItem, OrderStatus


customers_bp = Blueprint("customers", __name__, url_prefix="/account")

CAPTCHA_PURPOSE = "register"
THROTTLE_SCOPE = "customer"
RESET_SCOPE = "reset"
ORDERS_SHOWN = 50

# برای ایمیل ناموجود هم یک هش واقعی بررسی می‌شود تا زمان پاسخ چیزی لو ندهد
_DUMMY_HASH = generate_password_hash("timing-equalizer-not-a-real-password")


def download_limit():
    return int(current_app.config.get("DIGITAL_DOWNLOAD_LIMIT", 5))


# ------------------------------------------------------- ثبت‌نام و ورود

@customers_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_customer() is not None:
        return redirect(url_for("customers.dashboard"))

    form = RegisterForm()
    next_url = request.args.get("next", "")

    if form.validate_on_submit():
        if form.website.data:
            # ربات فیلد نامرئی را پر کرده است
            return redirect(url_for("customers.login"))

        if not verify_challenge(form.captcha.data, purpose=CAPTCHA_PURPOSE):
            flash("کد امنیتی اشتباه یا منقضی شده است.", "danger")
            form.captcha.data = ""
        elif Customer.query.filter_by(email=form.email.data).first():
            form.email.errors.append(
                "با این ایمیل قبلاً حساب ساخته شده است؛ وارد شوید."
            )
        else:
            customer = Customer(
                email=form.email.data, full_name=form.full_name.data
            )
            customer.set_password(form.password.data)
            db.session.add(customer)
            db.session.commit()

            login_customer(customer)
            flash("حساب شما ساخته شد و وارد شدید.", "success")

            return redirect(safe_next(
                next_url, url_for("customers.dashboard")
            ))

    return render_template("account/register.html", form=form, next_url=next_url)


@customers_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_customer() is not None:
        return redirect(url_for("customers.dashboard"))

    form = LoginForm()
    next_url = request.args.get("next", "")

    seconds = lock_remaining(THROTTLE_SCOPE)

    if seconds:
        flash(
            f"تلاش‌های ناموفق زیاد بود. حدود {seconds // 60 + 1} دقیقهٔ دیگر "
            "دوباره تلاش کنید.",
            "danger"
        )
        response = Response(
            render_template("account/login.html", form=form, next_url=next_url),
            status=429,
        )
        response.headers["Retry-After"] = str(seconds)
        return response

    if form.validate_on_submit():
        customer = Customer.query.filter_by(email=form.email.data).first()

        if customer is not None:
            valid = customer.check_password(form.password.data)
        else:
            check_password_hash(_DUMMY_HASH, form.password.data)
            valid = False

        if valid and customer.is_active:
            register_success(THROTTLE_SCOPE)
            login_customer(customer)

            return redirect(safe_next(
                next_url, url_for("customers.dashboard")
            ))

        register_failure(THROTTLE_SCOPE)
        flash("ایمیل یا رمز عبور اشتباه است.", "danger")

    return render_template("account/login.html", form=form, next_url=next_url)


# ------------------------------------------------------ بازیابی رمز عبور

def _reset_email_body(customer, link):
    return (
        f"سلام {customer.full_name}،\n\n"
        "برای ساخت رمز عبور تازه در CyberSite روی لینک زیر بزنید:\n"
        f"{link}\n\n"
        f"این لینک {reset_minutes()} دقیقه اعتبار دارد و فقط یک‌بار قابل استفاده است.\n"
        "اگر شما این درخواست را نداده‌اید، این ایمیل را نادیده بگیرید؛ "
        "رمز شما تغییری نمی‌کند."
    )


@customers_bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if current_customer() is not None:
        return redirect(url_for("customers.dashboard"))

    form = ForgotPasswordForm()

    seconds = lock_remaining(RESET_SCOPE)

    if seconds:
        flash(
            f"درخواست‌های بازیابی زیاد بود. حدود {seconds // 60 + 1} دقیقهٔ دیگر "
            "دوباره تلاش کنید.",
            "danger"
        )
        response = Response(
            render_template("account/forgot.html", form=form), status=429
        )
        response.headers["Retry-After"] = str(seconds)
        return response

    if form.validate_on_submit():
        # هر درخواست شمرده می‌شود تا کسی با این فرم ایمیل‌ها را بمباران نکند
        register_failure(RESET_SCOPE)

        if not verify_challenge(form.captcha.data, purpose=CAPTCHA_PURPOSE):
            flash("کد امنیتی اشتباه یا منقضی شده است.", "danger")
            form.captcha.data = ""
        else:
            customer = Customer.query.filter_by(email=form.email.data).first()

            if customer is not None and customer.is_active:
                link = base_url() + url_for(
                    "customers.reset_password", token=make_token(customer)
                )

                if is_configured():
                    send_mail(
                        customer.email,
                        "بازیابی رمز عبور CyberSite",
                        _reset_email_body(customer, link),
                    )
                else:
                    # ایمیل تنظیم نشده (مثلاً روی کامپیوتر خودتان): لینک در کنسول چاپ می‌شود
                    current_app.logger.warning(
                        "MAIL تنظیم نشده؛ لینک بازیابی رمز برای %s: %s",
                        customer.email, link
                    )

            # پاسخ همیشه یکسان است تا معلوم نشود کدام ایمیل‌ها حساب دارند
            flash(
                "اگر با این ایمیل حساب ساخته شده باشد، لینک بازیابی رمز برایش "
                "ارسال شد. پوشهٔ اسپم را هم نگاه کنید.",
                "success"
            )

            return redirect(url_for("customers.login"))

    return render_template("account/forgot.html", form=form)


@customers_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    customer = read_token(token)

    if customer is None:
        flash("لینک بازیابی نامعتبر یا منقضی شده است؛ دوباره درخواست دهید.", "danger")
        return redirect(url_for("customers.forgot_password"))

    form = ResetPasswordForm()

    if form.validate_on_submit():
        customer.set_password(form.password.data)
        db.session.commit()
        register_success(THROTTLE_SCOPE)   # قفل ورود احتمالی این IP باز می‌شود

        flash("رمز عبور تغییر کرد؛ با رمز جدید وارد شوید.", "success")
        return redirect(url_for("customers.login"))

    response = Response(render_template("account/reset.html", form=form, token=token))
    # توکن در آدرس است؛ نباید از طریق Referer به سایت دیگری برود
    response.headers["Referrer-Policy"] = "no-referrer"

    return response


@customers_bp.route("/captcha.png")
def captcha():
    response = Response(create_challenge(CAPTCHA_PURPOSE), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@customers_bp.route("/logout", methods=["POST"])
def logout():
    logout_customer()
    flash("از حساب خود خارج شدید.", "success")

    return redirect(url_for("home.index"))


# ------------------------------------------------------------ پنل مشتری

@customers_bp.route("/")
@customer_required
def dashboard():
    customer = current_customer()

    orders = Order.query.filter(
        Order.customer_id == customer.id
    ).order_by(Order.created_at.desc()).limit(ORDERS_SHOWN).all()

    downloads = [
        (order, item)
        for order in orders if order.status == OrderStatus.PAID
        for item in order.items if item.is_digital
    ]

    files = {}

    if downloads:
        ids = {item.product_id for _o, item in downloads if item.product_id}
        files = {
            product.id: product
            for product in Product.query.filter(Product.id.in_(ids)).all()
        } if ids else {}

    return render_template(
        "account/dashboard.html",
        customer=customer,
        orders=orders,
        downloads=downloads,
        files=files,
        limit=download_limit(),
    )


@customers_bp.route("/password", methods=["GET", "POST"])
@customer_required
def change_password():
    customer = current_customer()
    form = ChangePasswordForm()

    if form.validate_on_submit():
        if not customer.check_password(form.current_password.data):
            form.current_password.errors.append("رمز فعلی اشتباه است.")
        else:
            customer.set_password(form.password.data)
            db.session.commit()
            flash("رمز عبور تغییر کرد.", "success")

            return redirect(url_for("customers.dashboard"))

    return render_template("account/password.html", form=form)


# ------------------------------------------------------------- دانلود

def _counts_as_download():
    """درخواست ادامهٔ دانلود (Range از وسط فایل) یک دانلود تازه حساب نمی‌شود."""
    byte_range = request.range

    if byte_range is None or not byte_range.ranges:
        return True

    return byte_range.ranges[0][0] in (None, 0)


@customers_bp.route("/download/<int:item_id>")
@customer_required
def download(item_id):
    customer = current_customer()
    item = db.session.get(OrderItem, item_id)

    if item is None or not item.is_digital:
        abort(404)

    order = item.order

    # فقط خریدار همین سفارشِ پرداخت‌شده؛ برای بقیه وجودِ فایل هم لو نمی‌رود
    if order.customer_id != customer.id or order.status != OrderStatus.PAID:
        abort(404)

    product = db.session.get(Product, item.product_id) if item.product_id else None
    path = stored_path(product.file_name) if product and product.file_name else None

    if path is None or not path.is_file():
        abort(404)

    limit = download_limit()

    if _counts_as_download():
        # شمارش اتمیک؛ درخواست‌های هم‌زمان از سقف رد نمی‌شوند
        result = db.session.execute(
            update(OrderItem)
            .where(OrderItem.id == item.id, OrderItem.download_count < limit)
            .values(download_count=OrderItem.download_count + 1)
        )
        db.session.commit()

        if result.rowcount != 1:
            flash(
                "سقف دانلود این فایل تمام شده است؛ برای دانلود دوباره با ما "
                "تماس بگیرید.",
                "warning"
            )
            return redirect(url_for("customers.dashboard"))

    elif item.download_count >= limit:
        abort(403)

    response = send_from_directory(
        path.parent,
        path.name,
        as_attachment=True,
        download_name=product.file_title or path.name,
        mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"

    return response
