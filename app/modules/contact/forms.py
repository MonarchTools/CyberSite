from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.modules.admin.captcha import CAPTCHA_LENGTH
from app.utils import normalize_mobile


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class ContactForm(FlaskForm):
    name = StringField(
        "نام",
        filters=[_strip],
        validators=[DataRequired(), Length(min=2, max=100)]
    )

    email = StringField(
        "ایمیل",
        filters=[_strip],
        validators=[
            DataRequired(),
            Length(max=120),
            Regexp(
                r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$",
                message="ایمیل معتبر نیست."
            )
        ]
    )

    phone = StringField(
        "شمارهٔ موبایل (اختیاری)",
        filters=[normalize_mobile],
        validators=[
            Optional(),
            Regexp(
                r"^09\d{9}$",
                message="شمارهٔ موبایل معتبر نیست (مثال: 09121234567)."
            )
        ]
    )

    subject = StringField(
        "موضوع (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=150)]
    )

    message = TextAreaField(
        "پیام",
        filters=[_strip],
        validators=[
            DataRequired(),
            Length(min=10, max=2000, message="پیام باید بین ۱۰ تا ۲۰۰۰ کاراکتر باشد.")
        ]
    )

    captcha = StringField(
        "کد امنیتی",
        validators=[
            DataRequired(),
            Length(min=CAPTCHA_LENGTH, max=CAPTCHA_LENGTH + 4)
        ]
    )

    # تله برای ربات‌ها: برای انسان نامرئی است و باید خالی بماند
    website = StringField("وب‌سایت", validators=[Optional(), Length(max=200)])

    submit = SubmitField("ارسال پیام")
