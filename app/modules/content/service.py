from flask import current_app, g

from app.extensions import db
from app.modules.content.models import SiteContent
from app.modules.content.registry import FIELDS, default_for


def _stored():
    """همهٔ مقدارهای ذخیره‌شده؛ یک‌بار در هر درخواست."""
    if not hasattr(g, "_site_content"):
        try:
            g._site_content = {
                row.key: row.value for row in SiteContent.query.all()
            }
        except Exception:  # noqa: BLE001 - خرابی دیتابیس نباید صفحه را از کار بیندازد
            db.session.rollback()
            g._site_content = {}

    return g._site_content


def get_text(key):
    field = FIELDS.get(key)

    if field is None:
        return ""

    value = _stored().get(key)

    if value:
        return value

    return default_for(field, current_app.config)


def forget_cache():
    if hasattr(g, "_site_content"):
        del g._site_content
