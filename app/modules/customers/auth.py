"""ورود مشتری با نشست (session) جدا از Flask-Login مدیر.

مدیر و مشتری هم‌زمان در یک مرورگر می‌توانند وارد باشند و یکدیگر را خارج نمی‌کنند.
نشست Flask امضاشده است؛ پس مهاجم نمی‌تواند شناسهٔ مشتری را جعل کند.
"""

from functools import wraps
from urllib.parse import urlparse

from flask import flash, g, redirect, request, session, url_for

from app.extensions import db
from app.modules.customers.models import Customer


SESSION_KEY = "customer_id"


def current_customer():
    """مشتری واردشده یا None؛ در هر درخواست یک‌بار از دیتابیس خوانده می‌شود."""
    if hasattr(g, "_customer"):
        return g._customer

    customer = None
    raw = session.get(SESSION_KEY)

    if isinstance(raw, int):
        customer = db.session.get(Customer, raw)

        if customer is not None and not customer.is_active:
            customer = None

    g._customer = customer
    return customer


def login_customer(customer):
    session[SESSION_KEY] = customer.id
    session.permanent = True
    g._customer = customer


def logout_customer():
    session.pop(SESSION_KEY, None)
    g._customer = None


def safe_next(target, fallback):
    """فقط مسیر داخلی سایت پذیرفته می‌شود (جلوگیری از open redirect)."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return fallback

    if "\\" in target or urlparse(target).netloc:
        return fallback

    return target


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_customer() is None:
            flash("برای ادامه ابتدا وارد حساب کاربری شوید.", "warning")

            target = request.full_path if request.method == "GET" else request.path
            return redirect(url_for("customers.login", next=target.rstrip("?")))

        return view(*args, **kwargs)

    return wrapped
