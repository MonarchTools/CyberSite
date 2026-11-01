import re
from datetime import datetime, timezone


_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

_MOBILE_RE = re.compile(r"^(?:\+98|0098|98|0)?(9\d{9})$")


def to_latin_digits(value):
    return (value or "").translate(_DIGIT_MAP)


def normalize_mobile(value):
    """شمارهٔ موبایل را به شکل 09xxxxxxxxx درمی‌آورد؛ در غیر این‌صورت متن پاک‌شده را برمی‌گرداند."""
    cleaned = re.sub(r"[\s\-()]", "", to_latin_digits(value))
    match = _MOBILE_RE.match(cleaned)

    if match:
        return "0" + match.group(1)

    return cleaned


def format_rial(value):
    """۱۲۳۴۵۶۷ → «1,234,567 ریال»."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""

    return f"{number:,} ریال"


def utcnow_naive():
    """زمان UTC بدون tzinfo؛ با مقادیر ذخیره‌شده در SQLite هم‌خوان است."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
