from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField, StringField, SubmitField, TextAreaField
)
from wtforms.validators import DataRequired, Length, Optional


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class PostForm(FlaskForm):
    title = StringField(
        "عنوان",
        filters=[_strip],
        validators=[DataRequired(), Length(min=3, max=150)]
    )

    slug = StringField(
        "آدرس پست (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=80)]
    )

    excerpt = TextAreaField(
        "خلاصه (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=300)]
    )

    body = TextAreaField(
        "متن پست",
        validators=[
            DataRequired(),
            Length(min=10, max=20000, message="متن باید بین ۱۰ تا ۲۰٬۰۰۰ کاراکتر باشد.")
        ]
    )

    cover = FileField(
        "تصویر شاخص (اختیاری)",
        validators=[
            Optional(),
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                "فقط تصاویر JPG، PNG و WEBP مجاز هستند."
            )
        ]
    )

    remove_cover = BooleanField("حذف تصویر فعلی")

    is_published = BooleanField("منتشر شود")

    submit = SubmitField("ذخیره")
