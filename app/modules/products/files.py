"""فایل‌های قابل‌دانلودِ محصولات فایلی.

- فایل‌ها بیرون از پوشهٔ static و در instance/uploads/files نگهداری می‌شوند؛ فقط از مسیر
  دانلود (بعد از بررسی ورود و خرید) داده می‌شوند.
- نام ذخیره‌شده تصادفی است؛ نام اصلی فقط برای نمایش و هنگام دانلود استفاده می‌شود.
- فقط پسوندهای فهرست سفید پذیرفته می‌شوند.
"""

import os
import re
from pathlib import Path
from uuid import uuid4

from flask import current_app

from app.uploads import upload_folder


FOLDER = "files"

DEFAULT_EXTENSIONS = (
    "zip", "rar", "7z", "pdf", "epub", "mp3", "mp4", "txt",
    "docx", "xlsx", "pptx", "csv", "json", "py",
)

STORED_NAME = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{1,5}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f/\\]")


def allowed_extensions():
    configured = current_app.config.get("DIGITAL_ALLOWED_EXTENSIONS")
    return {e.lower().lstrip(".") for e in (configured or DEFAULT_EXTENSIONS)}


def max_bytes():
    return int(current_app.config.get("DIGITAL_FILE_MAX_MB", 200)) * 1024 * 1024


def display_name(original):
    """نام اصلی فایل بدون مسیر و نویسه‌های کنترلی (فقط برای نمایش و دانلود)."""
    name = _CONTROL.sub("", Path(original or "").name).strip()
    return name[:150] or "file"


def stored_path(stored_name):
    """مسیر فایل ذخیره‌شده؛ برای نام نامعتبر None."""
    if not stored_name or not STORED_NAME.fullmatch(stored_name):
        return None

    return upload_folder(FOLDER) / stored_name


def save_product_file(file):
    """(نام ذخیره‌شده، نام نمایشی، حجم بایت) یا None اگر فایلی انتخاب نشده.

    برای فایل نامعتبر ValueError با پیام فارسی.
    """
    if not file or not getattr(file, "filename", ""):
        return None

    title = display_name(file.filename)
    extension = title.rsplit(".", 1)[-1].lower() if "." in title else ""

    if extension not in allowed_extensions():
        raise ValueError(
            "این نوع فایل مجاز نیست. پسوندهای مجاز: "
            + "، ".join(sorted(allowed_extensions()))
        )

    stored = f"{uuid4().hex}.{extension}"
    path = upload_folder(FOLDER) / stored

    file.stream.seek(0)
    file.save(path)

    size = os.path.getsize(path)

    if size == 0:
        path.unlink(missing_ok=True)
        raise ValueError("فایل خالی است.")

    if size > max_bytes():
        path.unlink(missing_ok=True)
        raise ValueError(
            f"حجم فایل بیشتر از {current_app.config.get('DIGITAL_FILE_MAX_MB', 200)} مگابایت است."
        )

    return stored, title, size


def remove_product_file(stored_name):
    path = stored_path(stored_name)

    if path is not None and (path.is_file() or path.is_symlink()):
        path.unlink()
