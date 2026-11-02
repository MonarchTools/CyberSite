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
STORED_MEDIA_NAME = re.compile(r"^[a-f0-9]{32}\.(?:webp|mp4|webm)$")
VIDEO_CHUNK = 1024 * 1024


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


def is_stored_media_name(filename):
    return bool(filename) and bool(STORED_MEDIA_NAME.fullmatch(filename))


def sniff_video(file):
    """نوع واقعی ویدیو را از بایت‌های ابتدای فایل تشخیص می‌دهد: 'mp4'، 'webm' یا None."""
    stream = file.stream
    stream.seek(0)
    head = stream.read(12)
    stream.seek(0)

    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"

    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"

    return None


def save_video(file, folder_name, max_bytes):
    """ویدیوی MP4 یا WEBM را (پس از بررسی بایت‌های ابتدایی و حجم) ذخیره می‌کند.

    ویدیو بازکدگذاری نمی‌شود؛ پس فقط با نام تصادفی و نوع محتوای ثابت سرو می‌شود.
    پسوند را خود برنامه از روی محتوای واقعی تعیین می‌کند، نه نام فایل کاربر.
    """
    kind = sniff_video(file)

    if kind is None:
        raise ValueError("فقط ویدیوی MP4 یا WEBM مجاز است.")

    filename = f"{uuid4().hex}.{kind}"
    path = upload_folder(folder_name) / filename
    written = 0

    try:
        with open(path, "wb") as target:
            while True:
                chunk = file.stream.read(VIDEO_CHUNK)

                if not chunk:
                    break

                written += len(chunk)

                if written > max_bytes:
                    raise ValueError(
                        f"حجم ویدیو بیش از {max_bytes // (1024 * 1024)} مگابایت است."
                    )

                target.write(chunk)

    except BaseException:
        path.unlink(missing_ok=True)
        raise

    if written == 0:
        path.unlink(missing_ok=True)
        raise ValueError("فایل ویدیو خالی است.")

    return filename


def save_media(file, folder_name, max_video_bytes):
    """عکس یا ویدیو؛ برمی‌گرداند (نام فایل، 'image' یا 'video')."""
    if not file or not getattr(file, "filename", ""):
        return None, None

    if sniff_video(file):
        return save_video(file, folder_name, max_video_bytes), "video"

    return save_image(file, folder_name), "image"


def remove_media(filename, folder_name):
    if not is_stored_media_name(filename):
        return

    path = upload_folder(folder_name) / filename

    if path.is_symlink() or path.is_file():
        path.unlink()


def remove_image(filename, folder_name):
    """فقط نام‌های تولیدشدهٔ خود برنامه حذف می‌شوند (جلوگیری از path traversal)."""
    if not is_stored_name(filename):
        return

    path = upload_folder(folder_name) / filename

    if path.is_symlink() or path.is_file():
        path.unlink()
