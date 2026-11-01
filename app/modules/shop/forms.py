from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.utils import normalize_mobile


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class CheckoutForm(FlaskForm):
    full_name = StringField(
        "نام و نام خانوادگی",
        filters=[_strip],
        validators=[DataRequired(), Length(min=3, max=120)]
    )

    phone = StringField(
        "شمارهٔ موبایل",
        filters=[normalize_mobile],
        validators=[
            DataRequired(),
            Regexp(
                r"^09\d{9}$",
                message="شمارهٔ موبایل معتبر نیست (مثال: 09121234567)."
            )
        ]
    )

    email = StringField(
        "ایمیل (اختیاری)",
        filters=[_strip],
        validators=[
            Optional(),
            Length(max=120),
            Regexp(
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                message="ایمیل معتبر نیست."
            )
        ]
    )

    note = TextAreaField(
        "توضیحات سفارش (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=500)]
    )

    submit = SubmitField("ادامه و پرداخت")
