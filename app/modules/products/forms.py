
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, MultipleFileField
from wtforms import (
    BooleanField,
    StringField,
    TextAreaField,
    IntegerField,
    SelectField,
    SubmitField
)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Length,
    NumberRange,
    Optional
)


class ProductForm(FlaskForm):
    title = StringField(
        "نام محصول",
        validators=[
            DataRequired(),
            Length(max=150)
        ]
    )

    description = TextAreaField(
        "توضیحات",
        validators=[Optional()]
    )

    price = IntegerField(
        "قیمت (ریال)",
        validators=[
            InputRequired(),
            NumberRange(min=0, max=1_000_000_000_000)
        ]
    )

    stock = IntegerField(
        "موجودی",
        default=0,
        validators=[
            InputRequired(),
            NumberRange(min=0, max=1_000_000)
        ]
    )

    category_id = SelectField(
        "دسته‌بندی",
        coerce=int,
        validators=[DataRequired()]
    )

    is_digital = BooleanField("محصول فایلی (دانلودی)")

    # نوع و حجم فایل هنگام ذخیره بررسی می‌شود (app/modules/products/files.py)
    product_file = FileField(
        "فایل برای دانلود",
        validators=[Optional()]
    )

    image = FileField(
        "تصویر محصول",
        validators=[
            Optional(),
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                "فقط تصاویر JPG، PNG و WEBP مجاز هستند."
            )
        ]
    )

    # نوع واقعی فایل‌ها هنگام ذخیره با Pillow بررسی می‌شود
    gallery = MultipleFileField(
        "تصاویر بیشتر (اختیاری)",
        validators=[Optional()]
    )

    submit = SubmitField("ذخیره محصول")


class CategoryForm(FlaskForm):
    name = StringField(
        "نام دسته‌بندی",
        validators=[
            DataRequired(),
            Length(min=2, max=100)
        ]
    )

    submit = SubmitField("افزودن دسته‌بندی")
