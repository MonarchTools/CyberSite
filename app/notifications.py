"""اعلان ایمیلی برای مدیر و مشتری.

اصول:
- ارسال ایمیل هرگز نباید سفارش یا پیام را خراب کند؛ هر خطا فقط لاگ می‌شود.
- ارسال در یک ریسمان جدا انجام می‌شود تا کاربر منتظر سرور ایمیل نماند.
- متن ایمیل‌ها از قبل ساخته می‌شود و ریسمان به دیتابیس دسترسی ندارد.
- مقادیر هدر (موضوع، آدرس) از CR/LF پاک می‌شوند تا تزریق هدر ممکن نباشد.
"""

import logging
import re
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

from app.modules.shop.models import Fulfillment


log = logging.getLogger(__name__)

_NEWLINES = re.compile(r"[\r\n\x00]+")
_ADDRESS = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
BODY_LIMIT = 2000


def _clean(value, limit=200):
    return _NEWLINES.sub(" ", str(value or "")).strip()[:limit]


def _valid_address(value):
    value = _clean(value, 254)
    return value if _ADDRESS.match(value) else None


def is_configured(config=None):
    config = config or current_app.config
    return bool(config.get("MAIL_SERVER") and _valid_address(config.get("MAIL_FROM")))


def _site_url():
    return (current_app.config.get("SITE_URL") or "").rstrip("/")


def _rial(value):
    return f"{int(value):,} ریال"


# ---------------------------------------------------------------- ارسال

def _send_smtp(settings, message):
    """اتصال واقعی SMTP (در تست‌ها جایگزین می‌شود)."""
    security = settings["security"]
    timeout = settings["timeout"]

    if security == "ssl":
        client = smtplib.SMTP_SSL(settings["server"], settings["port"], timeout=timeout)
    else:
        client = smtplib.SMTP(settings["server"], settings["port"], timeout=timeout)

    try:
        if security == "starttls":
            client.starttls()

        if settings["username"]:
            client.login(settings["username"], settings["password"])

        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001 - بستن اتصال نباید خطای تازه بسازد
            pass


def _run(settings, message):
    try:
        _send_smtp(settings, message)
    except Exception:  # noqa: BLE001 - هر خطای ایمیل فقط لاگ می‌شود
        log.exception("ارسال ایمیل ناموفق بود (به: %s)", message["To"])


def send_mail(to, subject, body, *, reply_to=None):
    """یک ایمیل متنی می‌فرستد. اگر تنظیم نشده باشد یا خطا بدهد، بی‌صدا رد می‌شود."""
    try:
        config = current_app.config
        recipient = _valid_address(to)

        if not recipient or not is_configured():
            return False

        message = EmailMessage()
        message["From"] = _valid_address(config["MAIL_FROM"])
        message["To"] = recipient
        message["Subject"] = _clean(subject)

        reply = _valid_address(reply_to) if reply_to else None
        if reply:
            message["Reply-To"] = reply

        message.set_content(str(body)[:20_000])

        settings = {
            "server": config["MAIL_SERVER"],
            "port": int(config.get("MAIL_PORT") or 587),
            "username": config.get("MAIL_USERNAME") or "",
            "password": config.get("MAIL_PASSWORD") or "",
            "security": (config.get("MAIL_SECURITY") or "starttls").lower(),
            "timeout": int(config.get("MAIL_TIMEOUT") or 10),
        }

        if config.get("MAIL_ASYNC", True):
            threading.Thread(
                target=_run, args=(settings, message), daemon=True
            ).start()
        else:
            _run(settings, message)

        return True

    except Exception:  # noqa: BLE001
        log.exception("ساخت ایمیل ناموفق بود")
        return False


def _admin_address():
    return current_app.config.get("ADMIN_NOTIFY_EMAIL") or ""


# ------------------------------------------------------------- رویدادها

def notify_new_message(contact_message):
    if not _admin_address():
        return

    body = (
        "یک پیام تازه از فرم تماس رسید.\n\n"
        f"نام: {_clean(contact_message.name)}\n"
        f"ایمیل: {_clean(contact_message.email)}\n"
        f"موبایل: {_clean(contact_message.phone) or '—'}\n"
        f"موضوع: {_clean(contact_message.subject) or '—'}\n\n"
        f"{str(contact_message.message)[:BODY_LIMIT]}\n"
    )

    if _site_url():
        body += f"\nصندوق پیام‌ها: {_site_url()}/contact/manage\n"

    send_mail(
        _admin_address(),
        f"پیام جدید از {_clean(contact_message.name, 60)}",
        body,
        reply_to=contact_message.email,
    )


def notify_order_paid(order):
    items = "\n".join(
        f"- {_clean(item.title, 150)} × {item.quantity}" for item in order.items
    )

    if _admin_address():
        body = (
            f"سفارش شمارهٔ {order.id} پرداخت شد.\n\n"
            f"مبلغ: {_rial(order.total_rial)}\n"
            f"مشتری: {_clean(order.full_name)}\n"
            f"موبایل: {_clean(order.phone)}\n\n"
            f"اقلام:\n{items}\n"
        )

        if _site_url():
            body += f"\nمدیریت سفارش: {_site_url()}/shop/manage/orders/{order.id}\n"

        send_mail(_admin_address(), f"سفارش جدید #{order.id} ({_rial(order.total_rial)})", body)

    if order.email:
        body = (
            f"{_clean(order.full_name, 80)} عزیز، پرداخت شما با موفقیت انجام شد.\n\n"
            f"شمارهٔ سفارش: {order.id}\n"
            f"مبلغ: {_rial(order.total_rial)}\n"
            f"کد پیگیری پرداخت: {_clean(order.ref_id) or '—'}\n\n"
            f"اقلام:\n{items}\n"
        )

        if _site_url():
            body += f"\nپیگیری سفارش: {_site_url()}/shop/order/{order.public_code}\n"

        send_mail(order.email, f"رسید سفارش شمارهٔ {order.id}", body)


_STAGE_TEXT = {
    Fulfillment.SHIPPED: "ارسال شد",
    Fulfillment.DELIVERED: "تحویل داده شد",
}


def notify_fulfillment_change(order):
    """فقط برای مرحلهٔ ارسال و تحویل و فقط اگر مشتری ایمیل داده باشد."""
    text = _STAGE_TEXT.get(order.fulfillment)

    if not text or not order.email:
        return

    body = f"{_clean(order.full_name, 80)} عزیز، سفارش شمارهٔ {order.id} شما {text}.\n"

    if order.fulfillment == Fulfillment.SHIPPED and order.tracking_code:
        body += f"\nکد رهگیری: {_clean(order.tracking_code, 64)}\n"

    if _site_url():
        body += f"\nپیگیری سفارش: {_site_url()}/shop/order/{order.public_code}\n"

    send_mail(order.email, f"سفارش شمارهٔ {order.id} {text}", body)
