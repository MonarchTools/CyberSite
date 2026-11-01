"""ارتقای ساده و افزایشی دیتابیس.

``db.create_all()`` جدول‌های جدید را می‌سازد ولی به جدول‌های موجود ستون اضافه
نمی‌کند. این تابع ستون‌های جدیدِ تعریف‌شده را (فقط افزودن، هرگز حذف یا تغییر)
به جدول‌های موجود اضافه می‌کند تا پروژه تا زمان استفاده از Flask-Migrate
بدون پاک‌کردن دیتابیس به‌روز شود.
"""

from sqlalchemy import inspect, text

from app.extensions import db


# (جدول، ستون، نوع SQL)
ADDED_COLUMNS = (
    ("posts", "cover_image", "VARCHAR(64)"),
)


def upgrade_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    added = []

    for table, column, sql_type in ADDED_COLUMNS:
        if table not in tables:
            continue  # جدول تازه است و create_all آن را با ستون کامل ساخته

        existing = {col["name"] for col in inspector.get_columns(table)}

        if column in existing:
            continue

        with db.engine.begin() as connection:
            connection.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}')
            )

        added.append(f"{table}.{column}")

    return added
