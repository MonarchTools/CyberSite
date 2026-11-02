from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.modules.slides.models import is_safe_link


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class SlideForm(FlaskForm):
    title = StringField(
        "عنوان",
        filters=[_strip],
        validators=[DataRequired(), Length(min=2, max=80)]
    )

    caption = StringField(
        "توضیح کوتاه (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=200)]
    )

    link_url = StringField(
        "لینک (اختیاری)",
        filters=[_strip],
        validators=[Optional(), Length(max=300)]
    )

    # نوع واقعی فایل هنگام ذخیره از روی محتوا بررسی می‌شود
    media = FileField(
        "عکس یا ویدیو",
        validators=[
            Optional(),
            FileAllowed(
                ["jpg", "jpeg", "png", "webp", "mp4", "webm"],
                "فقط JPG، PNG، WEBP، MP4 و WEBM مجاز است."
            )
        ]
    )

    is_active = BooleanField("نمایش داده شود", default=True)

    submit = SubmitField("ذخیره")

    def validate_link_url(self, field):
        if field.data and not is_safe_link(field.data):
            raise ValidationError(
                "لینک باید با / (صفحهٔ همین سایت) یا https:// شروع شود."
            )
