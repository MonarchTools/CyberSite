"""ساخت و بازگردانی پشتیبان (دیتابیس SQLite + پوشهٔ آپلودها) در یک فایل زیپ.

این ماژول به Flask وابسته نیست و فقط با مسیر فایل‌ها کار می‌کند.

محتوای زیپ:
  manifest.json     اطلاعات نسخه و تعداد فایل‌ها
  database.sqlite3  نسخهٔ یکدست از دیتابیس (با API رسمی backup خود SQLite)
  uploads/...       همهٔ فایل‌های آپلودشده (عکس‌ها، ویدیوها، فایل‌های فروشی)

فایل .env (کلیدها و رمزها) عمداً داخل پشتیبان نیست.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


FORMAT_VERSION = 1
APP_NAME = "cybersite"

MANIFEST = "manifest.json"
DB_ENTRY = "database.sqlite3"
UPLOADS_PREFIX = "uploads/"

# جدول‌هایی که در هر پشتیبانِ سالم باید باشند
REQUIRED_TABLES = ("admins", "products", "orders", "customers")

MAX_ENTRIES = 200_000
COPY_CHUNK = 1024 * 1024


class BackupError(Exception):
    """خطایی که پیامش برای نمایش به مدیر مناسب است."""


def _now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ ساخت

def _snapshot_db(db_path, target):
    with closing(sqlite3.connect(str(db_path))) as source, \
            closing(sqlite3.connect(str(target))) as dest:
        source.backup(dest)


def _upload_files(uploads_dir):
    uploads_dir = Path(uploads_dir)

    if not uploads_dir.is_dir():
        return

    for path in sorted(uploads_dir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path, PurePosixPath(path.relative_to(uploads_dir)).as_posix()


def create_backup(db_path, uploads_dir, fileobj):
    """زیپ پشتیبان را در ``fileobj`` (فایل باز باینری) می‌نویسد و manifest را برمی‌گرداند."""
    db_path = Path(db_path)

    if not db_path.is_file():
        raise BackupError("فایل دیتابیس پیدا نشد.")

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / DB_ENTRY
        _snapshot_db(db_path, snapshot)

        count = 0
        size = 0

        with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, DB_ENTRY)

            for path, name in _upload_files(uploads_dir):
                archive.write(path, UPLOADS_PREFIX + name)
                count += 1
                size += path.stat().st_size

            manifest = {
                "app": APP_NAME,
                "format": FORMAT_VERSION,
                "created_at": _now().isoformat(timespec="seconds"),
                "upload_files": count,
                "upload_bytes": size,
            }
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False))

    return manifest


# ----------------------------------------------------------------- بررسی

def _safe_member(name):
    """نام داخل زیپ باید نسبی و بدون خروج از پوشه باشد."""
    if not name or "\\" in name or "\x00" in name or name.startswith("/"):
        return False

    parts = PurePosixPath(name).parts

    if not parts or ".." in parts or ":" in parts[0]:
        return False

    return True


def _is_symlink(info):
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def inspect_backup(zip_path, *, max_bytes):
    """زیپ را بدون استخراج بررسی می‌کند؛ manifest را برمی‌گرداند یا BackupError."""
    if not zipfile.is_zipfile(zip_path):
        raise BackupError("فایل انتخاب‌شده یک پشتیبان (زیپ) معتبر نیست.")

    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()

        if len(infos) > MAX_ENTRIES:
            raise BackupError("تعداد فایل‌های داخل پشتیبان بیش از حد است.")

        total = 0
        names = set()

        for info in infos:
            name = info.filename

            if not _safe_member(name) or _is_symlink(info):
                raise BackupError("پشتیبان شامل مسیر یا فایل ناامن است و رد شد.")

            if not (name in (MANIFEST, DB_ENTRY) or name.startswith(UPLOADS_PREFIX)):
                raise BackupError("پشتیبان شامل فایل ناشناخته است و رد شد.")

            total += info.file_size
            names.add(name)

        if total > max_bytes:
            raise BackupError("حجم باز‌شدهٔ پشتیبان بیش از سقف مجاز است.")

        if MANIFEST not in names or DB_ENTRY not in names:
            raise BackupError("این فایل پشتیبان CyberSite نیست (بخش‌های اصلی را ندارد).")

        try:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BackupError("اطلاعات پشتیبان خوانده نشد.")

    if not isinstance(manifest, dict) or manifest.get("app") != APP_NAME:
        raise BackupError("این فایل پشتیبان CyberSite نیست.")

    if manifest.get("format") != FORMAT_VERSION:
        raise BackupError("نسخهٔ این پشتیبان با برنامه سازگار نیست.")

    return manifest


def _check_database(path):
    try:
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("دیتابیس داخل پشتیبان خراب است.")

            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    except sqlite3.DatabaseError:
        raise BackupError("دیتابیس داخل پشتیبان قابل خواندن نیست.")

    missing = [t for t in REQUIRED_TABLES if t not in tables]

    if missing:
        raise BackupError("دیتابیس داخل پشتیبان کامل نیست: " + ", ".join(missing))


# ------------------------------------------------------------ بازگردانی

def _extract(zip_path, destination):
    """فقط بخش‌های شناخته‌شده را (فایل‌به‌فایل و با کنترل مسیر) استخراج می‌کند."""
    destination = Path(destination).resolve()

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.filename == MANIFEST:
                continue

            target = (destination / info.filename).resolve()

            if destination not in target.parents:
                raise BackupError("پشتیبان شامل مسیر ناامن است و رد شد.")

            target.parent.mkdir(parents=True, exist_ok=True)

            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, COPY_CHUNK)


def _swap_uploads(new_dir, uploads_dir):
    """پوشهٔ آپلودها را با نسخهٔ جدید عوض می‌کند و مسیر نسخهٔ قدیمی را برمی‌گرداند."""
    uploads_dir = Path(uploads_dir)
    old = uploads_dir.with_name(uploads_dir.name + ".replaced")

    if old.exists():
        shutil.rmtree(old)

    had_old = uploads_dir.exists()

    try:
        if had_old:
            os.replace(uploads_dir, old)

        if Path(new_dir).exists():
            shutil.move(str(new_dir), str(uploads_dir))
        else:
            uploads_dir.mkdir(parents=True)
    except OSError as error:
        if had_old and old.exists() and not uploads_dir.exists():
            os.replace(old, uploads_dir)

        raise BackupError(
            "جایگزینی پوشهٔ آپلودها ممکن نشد (فایل‌ها ممکن است در حال استفاده باشند): "
            f"{error}"
        )

    return old if had_old else None


def _undo_swap(uploads_dir, old):
    uploads_dir = Path(uploads_dir)

    if old is None:
        shutil.rmtree(uploads_dir, ignore_errors=True)
        return

    shutil.rmtree(uploads_dir, ignore_errors=True)
    os.replace(old, uploads_dir)


def restore_backup(zip_path, db_path, uploads_dir, safety_path, *, max_bytes):
    """پشتیبان را بازمی‌گرداند.

    ترتیب: بررسی کامل → نسخهٔ ایمنی از وضعیت فعلی (``safety_path``) →
    تعویض آپلودها → جایگزینی دیتابیس. اگر مرحلهٔ آخر شکست بخورد آپلودها برمی‌گردند.
    پیش از فراخوانی باید همهٔ اتصال‌های برنامه به دیتابیس بسته شده باشند.
    """
    db_path = Path(db_path)
    uploads_dir = Path(uploads_dir)

    manifest = inspect_backup(zip_path, max_bytes=max_bytes)

    work = Path(tempfile.mkdtemp(prefix="restore-", dir=str(db_path.parent)))

    try:
        _extract(zip_path, work)
        _check_database(work / DB_ENTRY)

        safety_path = Path(safety_path)
        safety_path.parent.mkdir(parents=True, exist_ok=True)

        with open(safety_path, "wb") as safety:
            create_backup(db_path, uploads_dir, safety)

        old_uploads = _swap_uploads(work / "uploads", uploads_dir)

        try:
            with closing(sqlite3.connect(str(work / DB_ENTRY))) as source, \
                    closing(sqlite3.connect(str(db_path))) as dest:
                source.backup(dest)
        except Exception:
            _undo_swap(uploads_dir, old_uploads)
            raise

        if old_uploads is not None:
            shutil.rmtree(old_uploads, ignore_errors=True)

    finally:
        shutil.rmtree(work, ignore_errors=True)

    return manifest


def prune_safety_backups(folder, keep=3):
    """فقط ``keep`` نسخهٔ ایمنی آخر را نگه می‌دارد."""
    files = sorted(Path(folder).glob("before-restore-*.zip"))

    for path in files[:-keep] if keep else files:
        try:
            path.unlink()
        except OSError:
            pass
