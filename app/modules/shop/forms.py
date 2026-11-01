from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.utils import normalize_mobile, to_latin_digits


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


class FulfillmentForm(FlaskForm):
    """تغییر مرحلهٔ ارسال توسط مدیر."""

    fulfillment = SelectField(
        "مرحله",
        choices=[],
        validators=[DataRequired()]
    )

    tracking_code = StringField(
        "کد رهگیری",
        filters=[lambda v: to_latin_digits(v.strip()) if isinstance(v, str) else v],
        validators=[
            Optional(),
            Length(max=64),
            Regexp(
                r"^[A-Za-z0-9\-_/. ]+$",
                message="کد رهگیری فقط می‌تواند حروف انگلیسی، عدد و - _ / . باشد."
            )
        ]
    )

    admin_note = TextAreaField(
        "یادداشت داخلی",
        filters=[_strip],
        validators=[Optional(), Length(max=1000)]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.modules.shop.models import Fulfillment

        self.fulfillment.choices = [
            (key, Fulfillment.LABELS[key]) for key in Fulfillment.ALL
        ]
