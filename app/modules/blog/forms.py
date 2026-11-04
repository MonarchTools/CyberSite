from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, MultipleFileField
from wtforms import (
    BooleanField, SelectField, StringField, SubmitField, TextAreaField
)
from wtforms.validators import DataRequired, Length, Optional


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class CategoryForm(FlaskForm):
    name = StringField(
        "نام دسته",
        filters=[_strip],
        validators=[DataRequired(), Length(min=2, max=60)]
    )

    submit = SubmitField("افزودن دسته")


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

    # گزینه‌ها در view پر می‌شوند (۰ = بدون دسته)
    category_id = SelectField(
        "دسته‌بندی", coerce=int, choices=[(0, "بدون دسته")], default=0
    )

    tags_text = StringField(
        "برچسب‌ها (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=250)]
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

    images = MultipleFileField(
        "عکس‌های داخل متن (اختیاری)",
        validators=[Optional()]
    )

    is_published = BooleanField("منتشر شود")

    submit = SubmitField("ذخیره")
