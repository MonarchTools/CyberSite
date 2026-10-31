
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField,
    TextAreaField,
    DecimalField,
    IntegerField,
    SelectField,
    SubmitField
)
from wtforms.validators import (
    DataRequired,
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

    price = DecimalField(
        "قیمت",
        places=2,
        validators=[
            DataRequired(),
            NumberRange(min=0)
        ]
    )

    stock = IntegerField(
        "موجودی",
        default=0,
        validators=[
            DataRequired(),
            NumberRange(min=0)
        ]
    )

    category_id = SelectField(
        "دسته‌بندی",
        coerce=int,
        validators=[DataRequired()]
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
