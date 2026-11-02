from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import login_required
from flask_wtf import FlaskForm

from app.extensions import db
from app.modules.content.models import SiteContent
from app.modules.content.registry import FIELDS, SECTIONS, clean_value, default_for
from app.modules.content.service import forget_cache


content_bp = Blueprint("content", __name__, url_prefix="/content")


def _rows(values, errors):
    config = current_app.config
    sections = []

    for title, fields in SECTIONS:
        sections.append((title, [
            {
                **field,
                "default_text": default_for(field, config),
                "value": values.get(field["key"], ""),
                "error": errors.get(field["key"]),
            }
            for field in fields
        ]))

    return sections


@content_bp.route("/manage", methods=["GET", "POST"])
@login_required
def manage_content():
    form = FlaskForm()
    stored = {row.key: row.value for row in SiteContent.query.all()}

    if request.method == "POST" and form.validate_on_submit():
        config = current_app.config
        cleaned, errors = {}, {}

        for key, field in FIELDS.items():
            value, error = clean_value(field, request.form.get(key, ""))
            cleaned[key] = value

            if error:
                errors[key] = error

        if errors:
            flash("برخی فیلدها معتبر نیستند؛ پایین صفحه را ببینید.", "danger")
            return render_template(
                "content/manage.html", form=form,
                sections=_rows(cleaned, errors)
            ), 400

        for key, field in FIELDS.items():
            value = cleaned[key]
            row = db.session.get(SiteContent, key)

            # خالی یا مساوی پیش‌فرض یعنی «برگرد به پیش‌فرض»
            if not value or value == default_for(field, config):
                if row is not None:
                    db.session.delete(row)
            elif row is None:
                db.session.add(SiteContent(key=key, value=value))
            elif row.value != value:
                row.value = value

        db.session.commit()
        forget_cache()

        flash("متن‌ها ذخیره شد.", "success")
        return redirect(url_for("content.manage_content"))

    return render_template(
        "content/manage.html", form=form, sections=_rows(stored, {})
    )
