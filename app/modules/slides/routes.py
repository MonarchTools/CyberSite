from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template,
    send_from_directory, url_for
)
from flask_login import login_required

from app.extensions import db
from app.modules.slides.forms import SlideForm
from app.modules.slides.models import HomeSlide
from app.uploads import (
    is_stored_media_name, remove_media, save_media, upload_folder
)


slides_bp = Blueprint("slides", __name__, url_prefix="/slides")

FOLDER = "slides"
MAX_SLIDES = 8
MAX_VIDEO_BYTES = 20 * 1024 * 1024


def _max_video_bytes():
    return current_app.config.get("SLIDE_VIDEO_MAX_BYTES", MAX_VIDEO_BYTES)


def _ordered():
    return HomeSlide.query.order_by(HomeSlide.position, HomeSlide.id).all()


def _renumber(slides):
    for index, slide in enumerate(slides):
        slide.position = index


# ------------------------------------------------------------- فایل عمومی

@slides_bp.route("/media/<filename>")
def media(filename):
    if not is_stored_media_name(filename):
        abort(404)

    response = send_from_directory(
        upload_folder(FOLDER), filename,
        max_age=31536000, conditional=True   # conditional: پخش و جلو/عقب‌کردن ویدیو
    )
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    return response


# ------------------------------------------------------------------ مدیریت

@slides_bp.route("/manage")
@login_required
def manage_slides():
    return render_template(
        "slides/manage.html", slides=_ordered(), max_slides=MAX_SLIDES
    )


@slides_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_slide():
    if HomeSlide.query.count() >= MAX_SLIDES:
        flash(f"حداکثر {MAX_SLIDES} اسلاید می‌توان داشت؛ یکی را حذف کنید.", "warning")
        return redirect(url_for("slides.manage_slides"))

    form = SlideForm()

    if form.validate_on_submit():
        if not (form.media.data and form.media.data.filename):
            form.media.errors.append("برای اسلاید جدید عکس یا ویدیو لازم است.")
        else:
            try:
                name, kind = save_media(form.media.data, FOLDER, _max_video_bytes())
            except ValueError as error:
                form.media.errors.append(str(error))
            else:
                slides = _ordered()
                slide = HomeSlide(
                    title=form.title.data,
                    caption=form.caption.data or None,
                    link_url=form.link_url.data or None,
                    media_type=kind,
                    filename=name,
                    position=len(slides),
                    is_active=bool(form.is_active.data),
                )

                try:
                    db.session.add(slide)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    remove_media(name, FOLDER)
                    raise

                flash("اسلاید اضافه شد.", "success")
                return redirect(url_for("slides.manage_slides"))

    return render_template(
        "slides/form.html", form=form, page_title="اسلاید جدید", slide=None
    )


@slides_bp.route("/edit/<int:slide_id>", methods=["GET", "POST"])
@login_required
def edit_slide(slide_id):
    slide = db.session.get(HomeSlide, slide_id)

    if slide is None:
        abort(404)

    form = SlideForm(obj=slide)

    if form.validate_on_submit():
        new_name = new_kind = None

        try:
            new_name, new_kind = save_media(
                form.media.data, FOLDER, _max_video_bytes()
            )
        except ValueError as error:
            form.media.errors.append(str(error))
        else:
            old_name = slide.filename

            slide.title = form.title.data
            slide.caption = form.caption.data or None
            slide.link_url = form.link_url.data or None
            slide.is_active = bool(form.is_active.data)

            if new_name:
                slide.filename = new_name
                slide.media_type = new_kind

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                remove_media(new_name, FOLDER)
                raise

            if new_name:
                remove_media(old_name, FOLDER)

            flash("اسلاید ویرایش شد.", "success")
            return redirect(url_for("slides.manage_slides"))

    return render_template(
        "slides/form.html", form=form, page_title="ویرایش اسلاید", slide=slide
    )


@slides_bp.route("/delete/<int:slide_id>", methods=["POST"])
@login_required
def delete_slide(slide_id):
    slide = db.session.get(HomeSlide, slide_id)

    if slide is None:
        abort(404)

    name = slide.filename

    db.session.delete(slide)
    db.session.flush()

    remaining = _ordered()
    _renumber(remaining)
    db.session.commit()

    remove_media(name, FOLDER)

    flash("اسلاید حذف شد.", "success")
    return redirect(url_for("slides.manage_slides"))


@slides_bp.route("/toggle/<int:slide_id>", methods=["POST"])
@login_required
def toggle_slide(slide_id):
    slide = db.session.get(HomeSlide, slide_id)

    if slide is None:
        abort(404)

    slide.is_active = not slide.is_active
    db.session.commit()

    return redirect(url_for("slides.manage_slides"))


@slides_bp.route("/move/<int:slide_id>/<direction>", methods=["POST"])
@login_required
def move_slide(slide_id, direction):
    if direction not in ("up", "down"):
        abort(404)

    slides = _ordered()
    ids = [slide.id for slide in slides]

    if slide_id not in ids:
        abort(404)

    index = ids.index(slide_id)
    target = index - 1 if direction == "up" else index + 1

    if 0 <= target < len(slides):
        slides[index], slides[target] = slides[target], slides[index]

    _renumber(slides)
    db.session.commit()

    return redirect(url_for("slides.manage_slides"))
