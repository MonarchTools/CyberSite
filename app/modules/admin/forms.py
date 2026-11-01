
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length

from app.modules.admin.captcha import CAPTCHA_LENGTH


class LoginForm(FlaskForm):
    username = StringField(
        "نام کاربری",
        validators=[
            DataRequired(),
            Length(min=3, max=80)
        ]
    )

    password = PasswordField(
        "رمز عبور",
        validators=[DataRequired()]
    )

    captcha = StringField(
        "کد امنیتی",
        validators=[
            DataRequired(),
            Length(min=CAPTCHA_LENGTH, max=CAPTCHA_LENGTH + 4)
        ]
    )

    submit = SubmitField("ورود به پنل")
