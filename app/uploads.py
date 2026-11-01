"""آپلود امن تصویر.

- فرمت واقعی با Pillow بررسی می‌شود (نه فقط پسوند) و ابعاد محدود است.
- تصویر دوباره ذخیره می‌شود (WEBP): متادیتا (EXIF، GPS) و هر داده‌ٔ اضافه‌ای که
  داخل فایل پنهان شده باشد حذف می‌شود و اندازه کوچک‌تر می‌شود.
- نام فایل ذخیره‌شده تصادفی (۳۲ رقم hex) است و نام اصلی کاربر هرگز استفاده نمی‌شود.
"""

import re
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 25_000_000
MAX_SIDE = 1600

STORED_NAME = re.compile(r"^[a-f0-9]{32}\.webp$")


def upload_folder(name):
    folder = Path(current_app.instance_path) / "uploads" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def is_stored_name(filename):
    return bool(filename) and bool(STORED_NAME.fullmatch(filename))


def save_image(file, folder_name):
    """فایل آپلودشده را اعتبارسنجی، پاک‌سازی و ذخیره می‌کند؛ نام فایل را برمی‌گرداند.

    اگر فایل خالی باشد None برمی‌گردد و برای خطا ValueError با پیام فارسی.
    """
    if not file or not getattr(file, "filename", ""):
        return None

    try:
        file.stream.seek(0)

        with Image.open(file.stream) as image:
            if image.format not in ALLOWED_FORMATS:
                raise ValueError("فقط تصاویر JPG، PNG و WEBP مجاز هستند.")

            width, height = image.size

            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ValueError("ابعاد تصویر بیش از حد مجاز است.")

            image.load()                                  # رمزگشایی کامل؛ فایل خراب اینجا خطا می‌دهد
            image = ImageOps.exif_transpose(image)        # چرخش درست بر اساس EXIF
            image.thumbnail((MAX_SIDE, MAX_SIDE))

            has_alpha = (
                image.mode in ("RGBA", "LA")
                or (image.mode == "P" and "transparency" in image.info)
            )
            image = image.convert("RGBA" if has_alpha else "RGB")

            filename = f"{uuid4().hex}.webp"

            # بدون exif/icc: فقط پیکسل‌ها ذخیره می‌شوند
            image.save(
                upload_folder(folder_name) / filename,
                format="WEBP",
                quality=85,
                method=4,
            )

    except ValueError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("فایل انتخاب‌شده تصویر معتبر نیست.")

    return filename


def remove_image(filename, folder_name):
    """فقط نام‌های تولیدشدهٔ خود برنامه حذف می‌شوند (جلوگیری از path traversal)."""
    if not is_stored_name(filename):
        return

    path = upload_folder(folder_name) / filename

    if path.is_symlink() or path.is_file():
        path.unlink()
