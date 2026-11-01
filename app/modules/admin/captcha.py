"""کپچای تصویری سمت سرور برای فرم ورود مدیر.

طراحی:
- متن کپچا فقط روی سرور ساخته می‌شود و هرگز به کلاینت نمی‌رسد؛ در دیتابیس
  فقط HMAC پاسخ نگه‌داری می‌شود (با SECRET_KEY).
- هر چالش یک‌بارمصرف است و بعد از ``CAPTCHA_TTL`` ثانیه منقضی می‌شود؛
  بنابراین تکرار (replay) یک پاسخ درست ممکن نیست.
- کوکی نشست فقط توکن تصادفی چالش را نگه می‌دارد، نه پاسخ را.
"""

import hashlib
import hmac
import io
import math
import secrets
import time

from flask import current_app, session
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.extensions import db
from app.modules.admin.models import CaptchaChallenge


CAPTCHA_LENGTH = 5
CAPTCHA_TTL = 180  # ثانیه
SESSION_KEY = "captcha_token"

# حروف و ارقام مبهم (I, O, 0, 1) حذف شده‌اند.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_rng = secrets.SystemRandom()

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
)

# ارقام فارسی و عربی هم پذیرفته می‌شوند (کاربر با کیبورد فارسی).
_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _random_text():
    return "".join(_rng.choice(ALPHABET) for _ in range(CAPTCHA_LENGTH))


def normalize_answer(value):
    return (value or "").translate(_DIGIT_MAP).strip().replace(" ", "").upper()


def _load_font(size):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow قدیمی‌تر از 10.1
        return ImageFont.load_default()


def _rand_color(low, high):
    return tuple(_rng.randint(low, high) for _ in range(3))


def render_captcha(text):
    """متن را به تصویر PNG (bytes) تبدیل می‌کند."""
    width, height = 200, 70
    background = _rand_color(225, 250)

    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)

    for _ in range(5):
        draw.line(
            [
                (_rng.randint(0, width), _rng.randint(0, height)),
                (_rng.randint(0, width), _rng.randint(0, height)),
            ],
            fill=_rand_color(150, 210),
            width=2,
        )

    font = _load_font(38)
    slot = (width - 20) // len(text)

    for index, char in enumerate(text):
        tile = Image.new("L", (64, 64), 0)
        tile_draw = ImageDraw.Draw(tile)
        left, top, right, bottom = tile_draw.textbbox((0, 0), char, font=font)
        tile_draw.text(
            (
                (64 - (right - left)) / 2 - left,
                (64 - (bottom - top)) / 2 - top,
            ),
            char,
            fill=255,
            font=font,
        )
        tile = tile.rotate(
            _rng.uniform(-28, 28),
            resample=Image.BICUBIC,
        )

        ink = Image.new("RGB", (64, 64), _rand_color(10, 110))
        x = 10 + index * slot - (64 - slot) // 2 + _rng.randint(-3, 3)
        y = (height - 64) // 2 + _rng.randint(-5, 5)
        canvas.paste(ink, (x, y), tile)

    # موج‌دار کردن تصویر
    waved = Image.new("RGB", (width, height), background)
    amplitude = _rng.uniform(2, 4)
    period = _rng.uniform(40, 70)
    phase = _rng.uniform(0, 2 * math.pi)

    for col in range(width):
        shift = int(amplitude * math.sin(2 * math.pi * col / period + phase))
        waved.paste(canvas.crop((col, 0, col + 1, height)), (col, shift))

    top_draw = ImageDraw.Draw(waved)

    for _ in range(3):
        top_draw.line(
            [
                (_rng.randint(0, width), _rng.randint(0, height)),
                (_rng.randint(0, width), _rng.randint(0, height)),
            ],
            fill=_rand_color(60, 160),
            width=2,
        )

    for _ in range(140):
        top_draw.point(
            (_rng.randint(0, width - 1), _rng.randint(0, height - 1)),
            fill=_rand_color(40, 180),
        )

    waved = waved.filter(ImageFilter.SMOOTH)

    buffer = io.BytesIO()
    waved.save(buffer, format="PNG")
    return buffer.getvalue()


def _answer_hash(token, answer):
    key = current_app.config["SECRET_KEY"].encode("utf-8")
    message = f"{token}:{answer}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def create_challenge():
    """چالش جدید می‌سازد، چالش قبلی همین نشست را باطل می‌کند و PNG برمی‌گرداند."""
    now = time.time()

    CaptchaChallenge.query.filter(
        CaptchaChallenge.expires_at < now
    ).delete(synchronize_session=False)

    previous = session.pop(SESSION_KEY, None)

    if previous:
        CaptchaChallenge.query.filter_by(token=previous).delete(
            synchronize_session=False
        )

    token = secrets.token_urlsafe(32)
    text = _random_text()

    db.session.add(
        CaptchaChallenge(
            token=token,
            answer_hash=_answer_hash(token, text),
            expires_at=now + CAPTCHA_TTL,
        )
    )
    db.session.commit()

    session[SESSION_KEY] = token

    return render_captcha(text)


def verify_challenge(answer):
    """پاسخ را بررسی می‌کند. چالش در هر حالت مصرف (حذف) می‌شود."""
    token = session.pop(SESSION_KEY, None)
    answer = normalize_answer(answer)

    if not token or len(answer) != CAPTCHA_LENGTH:
        if token:
            CaptchaChallenge.query.filter_by(token=token).delete(
                synchronize_session=False
            )
            db.session.commit()
        return False

    challenge = db.session.get(CaptchaChallenge, token)

    if challenge is None:
        return False

    expires_at = challenge.expires_at
    expected = challenge.answer_hash

    db.session.delete(challenge)
    db.session.commit()

    if expires_at < time.time():
        return False

    return hmac.compare_digest(expected, _answer_hash(token, answer))
