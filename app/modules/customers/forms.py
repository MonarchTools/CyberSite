from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import (
    DataRequired, EqualTo, Length, Optional, Regexp
)

from app.modules.admin.captcha import CAPTCHA_LENGTH


EMAIL_PATTERN = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
MIN_PASSWORD = 8


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _email(value):
    return value.strip().lower() if isinstance(value, str) else value


class RegisterForm(FlaskForm):
    full_name = StringField(
        "نام و نام خانوادگی",
        filters=[_strip],
        validators=[DataRequired(), Length(min=3, max=120)]
    )

    email = StringField(
        "ایمیل",
        filters=[_email],
        validators=[
            DataRequired(),
            Length(max=120),
            Regexp(EMAIL_PATTERN, message="ایمیل معتبر نیست.")
        ]
    )

    password = PasswordField(
        "رمز عبور",
        validators=[
            DataRequired(),
            Length(
                min=MIN_PASSWORD, max=128,
                message=f"رمز عبور باید حداقل {MIN_PASSWORD} کاراکتر باشد."
            )
        ]
    )

    password2 = PasswordField(
        "تکرار رمز عبور",
        validators=[
            DataRequired(),
            EqualTo("password", message="رمز عبور و تکرار آن یکی نیست.")
        ]
    )

    captcha = StringField(
        "کد امنیتی",
        validators=[
            DataRequired(),
            Length(min=CAPTCHA_LENGTH, max=CAPTCHA_LENGTH + 4)
        ]
    )

    # تلهٔ ربات: برای انسان نامرئی است و باید خالی بماند
    website = StringField("وب‌سایت", validators=[Optional(), Length(max=200)])

    submit = SubmitField("ساخت حساب")


class LoginForm(FlaskForm):
    email = StringField(
        "ایمیل",
        filters=[_email],
        validators=[DataRequired(), Length(max=120)]
    )

    password = PasswordField("رمز عبور", validators=[DataRequired()])

    submit = SubmitField("ورود")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("رمز فعلی", validators=[DataRequired()])

    password = PasswordField(
        "رمز جدید",
        validators=[
            DataRequired(),
            Length(
                min=MIN_PASSWORD, max=128,
                message=f"رمز عبور باید حداقل {MIN_PASSWORD} کاراکتر باشد."
            )
        ]
    )

    password2 = PasswordField(
        "تکرار رمز جدید",
        validators=[
            DataRequired(),
            EqualTo("password", message="رمز جدید و تکرار آن یکی نیست.")
        ]
    )

    submit = SubmitField("تغییر رمز")
