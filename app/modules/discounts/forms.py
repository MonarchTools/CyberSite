from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, DateField, IntegerField, SelectField, StringField,
    SubmitField
)
from wtforms.validators import (
    DataRequired, InputRequired, NumberRange, Optional, Regexp, ValidationError
)

from app.modules.discounts.models import DiscountKind
from app.modules.discounts.service import CODE_PATTERN, normalize_code


class DiscountForm(FlaskForm):
    code = StringField(
        "کد تخفیف",
        filters=[normalize_code],
        validators=[
            DataRequired(),
            Regexp(
                CODE_PATTERN.pattern,
                message="کد باید ۳ تا ۴۰ کاراکتر انگلیسی/عدد و - _ باشد (مثال: SUMMER20)."
            )
        ]
    )

    kind = SelectField(
        "نوع تخفیف",
        choices=[(key, DiscountKind.LABELS[key]) for key in DiscountKind.ALL],
        validators=[DataRequired()]
    )

    value = IntegerField(
        "مقدار (درصد یا ریال)",
        validators=[InputRequired(), NumberRange(min=1, max=1_000_000_000_000)]
    )

    min_order_rial = IntegerField(
        "حداقل مبلغ سبد (ریال)",
        default=0,
        validators=[Optional(), NumberRange(min=0, max=1_000_000_000_000)]
    )

    max_discount_rial = IntegerField(
        "سقف تخفیف برای کد درصدی (ریال، اختیاری)",
        validators=[Optional(), NumberRange(min=1, max=1_000_000_000_000)]
    )

    max_uses = IntegerField(
        "حداکثر دفعات استفاده (خالی = نامحدود)",
        validators=[Optional(), NumberRange(min=1, max=10_000_000)]
    )

    once_per_customer = BooleanField(
        "هر مشتری فقط یک‌بار بتواند استفاده کند", default=True
    )

    expires_on = DateField(
        "آخرین روز اعتبار (میلادی، خالی = بدون انقضا)",
        format="%Y-%m-%d",
        validators=[Optional()]
    )

    is_active = BooleanField("فعال", default=True)

    submit = SubmitField("ذخیره")

    def validate_value(self, field):
        if field.data is None:
            return

        if self.kind.data == DiscountKind.PERCENT and not 1 <= field.data <= 100:
            raise ValidationError("درصد باید بین ۱ تا ۱۰۰ باشد.")


class ApplyCodeForm(FlaskForm):
    """فقط برای CSRF و ورودی کد در سبد خرید."""
    code = StringField("کد تخفیف", validators=[DataRequired()])
    submit = SubmitField("اعمال")
