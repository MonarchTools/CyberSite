"""قفل تلاش ناموفق ورود، بر پایهٔ IP و ذخیره‌شده در جدول login_attempts.

- بعد از ``LOGIN_MAX_ATTEMPTS`` تلاش ناموفق (رمز یا کپچا) IP به
  ``LOGIN_LOCK_MINUTES`` دقیقه قفل می‌شود.
- شمارنده‌ای که بیش از همین مدت بدون تلاش جدید مانده باشد از نو شروع می‌شود.
- ورود موفق شمارنده را پاک می‌کند.
- افزایش شمارنده اتمیک است تا درخواست‌های هم‌زمان شمارش را گم نکنند.
"""

import time

from flask import current_app, request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.modules.admin.models import LoginAttempt


STALE_ROW_SECONDS = 24 * 3600


def _limits():
    config = current_app.config
    attempts = max(int(config.get("LOGIN_MAX_ATTEMPTS", 5)), 1)
    lock_seconds = max(int(config.get("LOGIN_LOCK_MINUTES", 15)), 1) * 60
    return attempts, lock_seconds


def client_ip():
    return (request.remote_addr or "unknown")[:45]


def _get_row(ip, create=False):
    row = LoginAttempt.query.filter_by(ip_address=ip).first()

    if row is None and create:
        row = LoginAttempt(
            ip_address=ip,
            failed_attempts=0,
            updated_at=time.time(),
        )
        db.session.add(row)

        try:
            db.session.flush()
        except IntegrityError:
            # درخواست هم‌زمان دیگری همین ردیف را ساخته است
            db.session.rollback()
            row = LoginAttempt.query.filter_by(ip_address=ip).first()

    return row


def lock_remaining():
    """ثانیه‌های باقی‌ماندهٔ قفل؛ اگر قفل نباشد 0."""
    row = _get_row(client_ip())

    if row is None:
        return 0

    now = time.time()

    if row.locked_until and row.locked_until > now:
        return int(row.locked_until - now) + 1

    if row.locked_until:
        # قفل تمام شده؛ شمارنده از نو شروع می‌شود
        row.failed_attempts = 0
        row.locked_until = None
        row.updated_at = now
        db.session.commit()

    return 0


def register_failure():
    max_attempts, lock_seconds = _limits()
    now = time.time()

    # ردیف‌های قدیمیِ قفل‌نشده پاک می‌شوند تا جدول بزرگ نشود
    LoginAttempt.query.filter(
        LoginAttempt.updated_at < now - STALE_ROW_SECONDS,
        LoginAttempt.locked_until.is_(None),
    ).delete(synchronize_session=False)

    row = _get_row(client_ip(), create=True)

    if row.locked_until and row.locked_until > now:
        db.session.commit()
        return

    if row.updated_at < now - lock_seconds:
        row.failed_attempts = 0
        row.locked_until = None

    db.session.execute(
        update(LoginAttempt)
        .where(LoginAttempt.id == row.id)
        .values(
            failed_attempts=LoginAttempt.failed_attempts + 1,
            updated_at=now,
        )
    )
    db.session.flush()
    db.session.refresh(row)

    if row.failed_attempts >= max_attempts:
        row.locked_until = now + lock_seconds

    db.session.commit()


def register_success():
    LoginAttempt.query.filter_by(ip_address=client_ip()).delete(
        synchronize_session=False
    )
    db.session.commit()
