from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.modules.admin.captcha import CAPTCHA_LENGTH


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class CommentForm(FlaskForm):
    name = StringField(
        "نام",
        filters=[_strip],
        validators=[DataRequired(), Length(min=2, max=60)]
    )

    body = TextAreaField(
        "نظر شما",
        filters=[_strip],
        validators=[
            DataRequired(),
            Length(min=5, max=1000, message="نظر باید بین ۵ تا ۱۰۰۰ کاراکتر باشد.")
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

    submit = SubmitField("ارسال نظر")
