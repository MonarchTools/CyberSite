
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length


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

    submit = SubmitField("ورود به پنل")
