from PIL import Image, UnidentifiedImageError
from pathlib import Path
from uuid import uuid4
import re

from flask import (
    Blueprint, render_template, redirect,
    url_for, flash, request, current_app,
    send_from_directory, abort
)
from flask_login import login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.modules.products.models import Product, Category
from app.modules.products.forms import ProductForm, CategoryForm


products_bp = Blueprint(
    "products",
    __name__,
    url_prefix="/products"
)


def get_upload_folder():
    folder = Path(current_app.instance_path) / "uploads" / "products"
    folder.mkdir(parents=True, exist_ok=True)
    return folder



def save_product_image(file):
    if not file or not file.filename:
        return None

    allowed_formats = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
    }

    original_name = secure_filename(file.filename)
    extension = Path(original_name).suffix.lower()

    if extension not in allowed_formats:
        raise ValueError("فرمت تصویر مجاز نیست.")

    try:
        file.stream.seek(0)

        with Image.open(file.stream) as image:
            actual_format = image.format
            width, height = image.size

            if actual_format != allowed_formats[extension]:
                raise ValueError(
                    "محتوای فایل با پسوند آن مطابقت ندارد."
                )

            if width <= 0 or height <= 0:
                raise ValueError("ابعاد تصویر معتبر نیست.")

            if width * height > 25_000_000:
                raise ValueError("ابعاد تصویر بیش از حد مجاز است.")

            image.verify()

        file.stream.seek(0)

    except ValueError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("فایل انتخاب‌شده تصویر معتبر نیست.")

    filename = f"{uuid4().hex}{extension}"

    file.save(get_upload_folder() / filename)

    return filename


def remove_product_image(filename):
    if not filename:
        return

    # فقط نام فایل‌های تولیدشده با UUID پذیرفته می‌شوند
    pattern = r"^[a-f0-9]{32}\.(jpg|jpeg|png|webp)$"

    if not re.fullmatch(pattern, filename):
        current_app.logger.warning(
            "Rejected unsafe image filename: %r",
            filename
        )
        return

    folder = get_upload_folder()
    path = folder / filename

    # اگر فایل یا لینک نمادین وجود داشته باشد، فقط همان ورودی حذف می‌شود
    if path.is_symlink() or path.is_file():
        path.unlink()

@products_bp.route("/")
def index():
    products = Product.query.order_by(
        Product.created_at.desc()
    ).all()

    return render_template(
        "products/list.html",
        products=products
    )


@products_bp.route("/manage")
@login_required
def manage_products():
    products = Product.query.order_by(
        Product.created_at.desc()
    ).all()

    categories = Category.query.order_by(
        Category.name
    ).all()

    category_form = CategoryForm()

    return render_template(
        "products/manage.html",
        products=products,
        categories=categories,
        category_form=category_form
    )


@products_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_product():
    form = ProductForm()

    categories = Category.query.order_by(Category.name).all()
    form.category_id.choices = [
        (category.id, category.name)
        for category in categories
    ]

    if not categories:
        flash("ابتدا یک دسته‌بندی ایجاد کنید.", "warning")
        return redirect(url_for("products.manage_products"))

    if form.validate_on_submit():
        image_filename = None

        try:
            image_filename = save_product_image(form.image.data)

            product = Product(
                title=form.title.data.strip(),
                description=form.description.data,
                price=form.price.data,
                stock=form.stock.data,
                category_id=form.category_id.data,
                image_filename=image_filename
            )

            db.session.add(product)
            db.session.commit()

            flash("محصول با موفقیت اضافه شد.", "success")
            return redirect(url_for("products.manage_products"))


        except ValueError as error:
            db.session.rollback()

            if image_filename:
                remove_product_image(image_filename)

            flash(str(error), "danger")



        except Exception:
            db.session.rollback()

            if image_filename:
                remove_product_image(image_filename)

            current_app.logger.exception("Product creation failed")
            flash("ذخیره محصول انجام نشد.", "danger")

    return render_template(
        "products/product_form.html",
        form=form,
        page_title="افزودن محصول"
    )




@products_bp.route("/edit/<int:product_id>", methods=["GET", "POST"])
@login_required


def edit_product(product_id):
    product = db.session.get(Product, product_id)

    if product is None:
        abort(404)

    form = ProductForm(obj=product)

    categories = Category.query.order_by(Category.name).all()
    form.category_id.choices = [
        (category.id, category.name)
        for category in categories
    ]

    if request.method == "GET":
        form.category_id.data = product.category_id

    if form.validate_on_submit():
        old_image = product.image_filename
        new_image = None

        try:
            if form.image.data:
                new_image = save_product_image(form.image.data)

            product.title = form.title.data.strip()
            product.description = form.description.data
            product.price = form.price.data
            product.stock = form.stock.data
            product.category_id = form.category_id.data

            if new_image:
                product.image_filename = new_image

            db.session.commit()

            if new_image and old_image:
                remove_product_image(old_image)

            flash("محصول ویرایش شد.", "success")
            return redirect(url_for("products.manage_products"))







        except ValueError as error:
            db.session.rollback()

            if new_image:
                remove_product_image(new_image)

            flash(str(error), "danger")









        except Exception:
            db.session.rollback()

            if new_image:
                remove_product_image(new_image)

            current_app.logger.exception("Product update failed")
            flash("ویرایش محصول انجام نشد.", "danger")

    return render_template(
        "products/product_form.html",
        form=form,
        page_title="ویرایش محصول",
        product=product
    )


@products_bp.route("/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)

    if product is None:
        abort(404)

    image_filename = product.image_filename

    try:
        db.session.delete(product)
        db.session.commit()

        if image_filename:
            remove_product_image(image_filename)

        flash("محصول حذف شد.", "success")

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Product deletion failed")
        flash("حذف محصول انجام نشد.", "danger")

    return redirect(url_for("products.manage_products"))


@products_bp.route("/categories/create", methods=["POST"])
@login_required
def create_category():
    form = CategoryForm()

    if form.validate_on_submit():
        name = form.name.data.strip()

        existing = Category.query.filter_by(name=name).first()

        if existing:
            flash("این دسته‌بندی قبلاً ثبت شده است.", "warning")
        else:
            db.session.add(Category(name=name))
            db.session.commit()
            flash("دسته‌بندی اضافه شد.", "success")

    else:
        flash("نام دسته‌بندی معتبر نیست.", "danger")

    return redirect(url_for("products.manage_products"))


@products_bp.route("/categories/delete/<int:category_id>", methods=["POST"])
@login_required
def delete_category(category_id):
    category = db.session.get(Category, category_id)

    if category is None:
        abort(404)

    if category.products:
        flash(
            "این دسته‌بندی محصول دارد؛ ابتدا محصولات آن را جابه‌جا یا حذف کنید.",
            "warning"
        )
    else:
        db.session.delete(category)
        db.session.commit()
        flash("دسته‌بندی حذف شد.", "success")

    return redirect(url_for("products.manage_products"))


@products_bp.route("/image/<path:filename>")
def product_image(filename):
    return send_from_directory(
        get_upload_folder(),
        filename
    )
