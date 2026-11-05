import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request,
    send_file, session, url_for
)
from flask_login import current_user, login_required, logout_user

from app.db_upgrade import upgrade_schema
from app.extensions import db
from app.modules.admin.throttle import (
    lock_remaining, register_failure, register_success
)
from app.modules.backup.archive import (
    BackupError, create_backup, prune_safety_backups, restore_backup
)


backup_bp = Blueprint("backup", __name__, url_prefix="/admin/backup")

THROTTLE_SCOPE = "backup"
STALE_AFTER_DAYS = 7


def _db_path():
    """مسیر فایل دیتابیس SQLite یا None (برای MySQL/PostgreSQL پشتیبان داخلی نداریم)."""
    url = db.engine.url

    if not url.drivername.startswith("sqlite"):
        return None

    if not url.database or url.database == ":memory:":
        return None

    return Path(url.database)


def _uploads_dir():
    return Path(current_app.instance_path) / "uploads"


def _backups_dir():
    folder = Path(current_app.instance_path) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _max_bytes():
    return int(current_app.config.get("BACKUP_MAX_MB", 500)) * 1024 * 1024


def _marker():
    return _backups_dir() / "last_backup.txt"


def last_backup_at():
    """زمان آخرین دانلود پشتیبان (UTC) یا None."""
    try:
        return datetime.fromisoformat(_marker().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def backup_is_stale():
    """True اگر هرگز پشتیبان نگرفته‌اید یا بیش از ۷ روز گذشته است."""
    last = last_backup_at()

    if last is None:
        return True

    return (datetime.now(timezone.utc) - last).days >= STALE_AFTER_DAYS


def _folder_stats(folder):
    count = 0
    size = 0

    if folder.is_dir():
        for path in folder.rglob("*"):
            if path.is_file():
                count += 1
                size += path.stat().st_size

    return count, size


@backup_bp.route("/")
@login_required
def index():
    path = _db_path()
    files, upload_bytes = _folder_stats(_uploads_dir())

    return render_template(
        "backup/index.html",
        supported=path is not None,
        db_bytes=path.stat().st_size if path and path.exists() else 0,
        upload_files=files,
        upload_bytes=upload_bytes,
        last=last_backup_at(),
        stale=backup_is_stale(),
        max_mb=int(current_app.config.get("BACKUP_MAX_MB", 500)),
    )


@backup_bp.route("/download", methods=["POST"])
@login_required
def download():
    path = _db_path()

    if path is None:
        flash("پشتیبان‌گیری داخلی فقط برای دیتابیس SQLite است.", "danger")
        return redirect(url_for("backup.index"))

    spool = tempfile.TemporaryFile()

    try:
        create_backup(path, _uploads_dir(), spool)
    except BackupError as error:
        spool.close()
        flash(str(error), "danger")
        return redirect(url_for("backup.index"))

    spool.seek(0)
    now = datetime.now(timezone.utc)

    try:
        _marker().write_text(now.isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass

    return send_file(
        spool,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"cybersite-backup-{now:%Y%m%d-%H%M%S}.zip",
        max_age=0,
    )


@backup_bp.route("/restore", methods=["POST"])
@login_required
def restore():
    path = _db_path()

    if path is None:
        flash("بازگردانی داخلی فقط برای دیتابیس SQLite است.", "danger")
        return redirect(url_for("backup.index"))

    seconds = lock_remaining(THROTTLE_SCOPE)

    if seconds:
        flash(f"تلاش‌های ناموفق زیاد بود. حدود {seconds // 60 + 1} دقیقهٔ دیگر امتحان کنید.", "danger")
        return redirect(url_for("backup.index"))

    if not current_user.check_password(request.form.get("password", "")):
        register_failure(THROTTLE_SCOPE)
        flash("رمز عبور مدیر اشتباه است.", "danger")
        return redirect(url_for("backup.index"))

    register_success(THROTTLE_SCOPE)

    upload = request.files.get("backup_file")

    if request.form.get("confirm") != "y":
        flash("برای بازگردانی باید تأیید را تیک بزنید.", "danger")
        return redirect(url_for("backup.index"))

    if not upload or not upload.filename:
        flash("فایل پشتیبان را انتخاب کنید.", "danger")
        return redirect(url_for("backup.index"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="upload-", dir=str(path.parent)))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safety = _backups_dir() / f"before-restore-{stamp}.zip"

    try:
        zip_path = tmp_dir / "upload.zip"
        upload.save(zip_path)

        # همهٔ اتصال‌ها به دیتابیس بسته می‌شوند تا فایل بی‌خطر جایگزین شود
        db.session.remove()
        db.engine.dispose()

        try:
            restore_backup(zip_path, path, _uploads_dir(), safety, max_bytes=_max_bytes())
        finally:
            # حتی اگر بازگردانی شکست بخورد، دیتابیس آمادهٔ استفاده می‌ماند
            db.create_all()
            upgrade_schema()
            prune_safety_backups(_backups_dir())

    except BackupError as error:
        flash(str(error), "danger")
        return redirect(url_for("backup.index"))

    except Exception:
        current_app.logger.exception("Restore failed")
        flash("بازگردانی ناموفق بود؛ اطلاعات فعلی دست‌نخورده مانده است.", "danger")
        return redirect(url_for("backup.index"))

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # حساب مدیرِ داخل پشتیبان ممکن است با حساب فعلی فرق داشته باشد
    logout_user()
    session.clear()
    flash("پشتیبان با موفقیت بازگردانی شد. دوباره وارد شوید.", "success")

    return redirect(url_for("admin.login"))
