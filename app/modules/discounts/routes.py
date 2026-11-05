from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for
)
from flask_login import login_required

from app.extensions import db
from app.modules.discounts.forms import DiscountForm
from app.modules.discounts.models import DiscountCode
from app.modules.discounts.service import end_of_day
from app.modules.shop.models import Order


discounts_bp = Blueprint("discounts", __name__, url_prefix="/discounts")


def _fill(code, form):
    code.code = form.code.data
    code.kind = form.kind.data
    code.value = form.value.data
    code.min_order_rial = form.min_order_rial.data or 0
    code.max_discount_rial = form.max_discount_rial.data or None
    code.max_uses = form.max_uses.data or None
    code.once_per_customer = bool(form.once_per_customer.data)
    code.expires_at = end_of_day(form.expires_on.data)
    code.is_active = bool(form.is_active.data)


def _code_taken(text, ignore_id=None):
    query = DiscountCode.query.filter(DiscountCode.code == text)

    if ignore_id is not None:
        query = query.filter(DiscountCode.id != ignore_id)

    return query.first() is not None


@discounts_bp.route("/manage")
@login_required
def manage():
    codes = DiscountCode.query.order_by(DiscountCode.created_at.desc()).all()
    return render_template("discounts/manage.html", codes=codes)


@discounts_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    form = DiscountForm()

    if form.validate_on_submit():
        if _code_taken(form.code.data):
            form.code.errors.append("این کد قبلاً ساخته شده است.")
        else:
            code = DiscountCode()
            _fill(code, form)
            db.session.add(code)
            db.session.commit()

            flash("کد تخفیف ساخته شد.", "success")
            return redirect(url_for("discounts.manage"))

    return render_template(
        "discounts/form.html", form=form, page_title="کد تخفیف جدید"
    )


@discounts_bp.route("/edit/<int:code_id>", methods=["GET", "POST"])
@login_required
def edit(code_id):
    code = db.session.get(DiscountCode, code_id)

    if code is None:
        abort(404)

    form = DiscountForm(obj=code) if request.method == "GET" else DiscountForm()

    if request.method == "GET":
        form.expires_on.data = code.expires_at.date() if code.expires_at else None

    if form.validate_on_submit():
        if _code_taken(form.code.data, ignore_id=code.id):
            form.code.errors.append("این کد قبلاً ساخته شده است.")
        else:
            _fill(code, form)
            db.session.commit()

            flash("کد تخفیف به‌روزرسانی شد.", "success")
            return redirect(url_for("discounts.manage"))

    return render_template(
        "discounts/form.html", form=form, page_title="ویرایش کد تخفیف", code=code
    )


@discounts_bp.route("/toggle/<int:code_id>", methods=["POST"])
@login_required
def toggle(code_id):
    code = db.session.get(DiscountCode, code_id)

    if code is None:
        abort(404)

    code.is_active = not code.is_active
    db.session.commit()

    flash("کد فعال شد." if code.is_active else "کد غیرفعال شد.", "success")
    return redirect(url_for("discounts.manage"))


@discounts_bp.route("/delete/<int:code_id>", methods=["POST"])
@login_required
def delete(code_id):
    code = db.session.get(DiscountCode, code_id)

    if code is None:
        abort(404)

    in_orders = db.session.query(Order.id).filter(
        Order.discount_code_id == code.id
    ).first()

    if in_orders:
        flash(
            "این کد در سفارش‌ها استفاده شده و حذف نمی‌شود؛ آن را غیرفعال کنید.",
            "warning"
        )
        return redirect(url_for("discounts.manage"))

    db.session.delete(code)
    db.session.commit()

    flash("کد تخفیف حذف شد.", "success")
    return redirect(url_for("discounts.manage"))
