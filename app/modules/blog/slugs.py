"""ساخت آدرس (slug) خوانا برای پست‌ها؛ حروف فارسی و لاتین و عدد و خط تیره."""

import re
import unicodedata


# با مسیرهای مدیریت یکی نشوند
RESERVED = {
    "manage", "create", "edit", "delete", "new",
    "feed", "rss", "page", "image",
}

_NON_WORD = re.compile(r"[^\w\-]+", re.UNICODE)
_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک"})


def slugify(value, max_length=80):
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    value = value.translate(_ARABIC_TO_PERSIAN)
    value = value.replace("‌", "-")          # نیم‌فاصله
    value = re.sub(r"[\s_]+", "-", value)
    value = _NON_WORD.sub("", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")

    return value[:max_length].strip("-")
